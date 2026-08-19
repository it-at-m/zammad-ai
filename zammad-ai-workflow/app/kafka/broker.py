"""Kafka router setup for Zammad AI ticket events."""

from collections.abc import Callable
from logging import Logger

from faststream import AckPolicy
from faststream.exceptions import AckMessage
from faststream.kafka.fastapi import Context, KafkaRouter
from faststream.kafka.prometheus import KafkaPrometheusMiddleware
from faststream.security import BaseSecurity
from prometheus_client import REGISTRY
from pydantic import ValidationError

from app.action.service import ActionService, get_action_service
from app.answer.service import AnswerService, get_answer_service
from app.errors import KafkaPayloadError
from app.kafka.helper import (
    _handle_processing_exception,
    _parse_original_group_id,
    _parse_retry_count,
    _reschedule_retry_event,
    _restore_ticket_group,
    _safe_ticket_id,
    _sleep_until_retry_after,
)
from app.models.kafka import Event
from app.models.triage import TriageResult
from app.models.zammad import ZammadTicket
from app.settings import ZammadAISettings
from app.triage.triage import TriageService, get_triage_service
from app.utils.logging import getLogger
from app.utils.status import track_activity
from app.zammad.base import BaseZammadClient, TicketNotFoundError, ZammadConnectionError, ZammadRetryableError

from .security import setup_security

logger: Logger = getLogger(name="zammad-ai.kafka.broker")


async def _process_ticket_event(
    *,
    settings: ZammadAISettings,
    triage_service: TriageService,
    action_service: ActionService,
    event: Event | dict[str, object],
    group_state: dict[str, int | None],
) -> None:
    """Parse and process a Kafka event."""
    if isinstance(event, Event):
        raw_request_type = event.request_type
        raw_action = event.action
        raw_ticket_id = _safe_ticket_id(event.ticket)
    else:
        raw_request_type = event.get("anliegenart") or event.get("requestType") or event.get("request_type")
        raw_action = event.get("action")
        raw_ticket_id = _safe_ticket_id(event.get("ticket"))
    logger.debug(
        "Received Kafka event",
        extra={
            "handler_stage": "event_received",
            "request_type": None if raw_request_type is None else str(raw_request_type),
            "action": None if raw_action is None else str(raw_action),
            "ticket_id": raw_ticket_id,
        },
    )

    try:
        parsed_event: Event = Event.model_validate(event)
    except ValidationError as e:
        logger.error(
            "Failed to parse Kafka event payload",
            extra={"handler_stage": "payload_validation_failed"},
            exc_info=True,
        )
        raise AckMessage() from e

    if parsed_event.request_type not in settings.kafka.event_processing.valid_request_types:
        logger.info(
            "Skipping event with unsupported request type",
            extra={
                "handler_stage": "request_type_filter",
                "request_type": parsed_event.request_type,
                "action": parsed_event.action,
                "ticket_id": _safe_ticket_id(parsed_event.ticket),
            },
        )
        raise AckMessage()

    if parsed_event.action not in settings.kafka.event_processing.valid_action_types:
        logger.info(
            "Skipping event with unsupported action type",
            extra={
                "handler_stage": "action_filter",
                "request_type": parsed_event.request_type,
                "action": parsed_event.action,
                "ticket_id": _safe_ticket_id(parsed_event.ticket),
            },
        )
        raise AckMessage()

    try:
        ticket_id = int(parsed_event.ticket)
    except TypeError, ValueError:
        raise KafkaPayloadError("Invalid ticket id in Kafka payload")

    zammad_client: BaseZammadClient = triage_service.zammad_client
    try:
        ticket: ZammadTicket = await zammad_client.get_ticket(id=ticket_id)
    except TicketNotFoundError as e:
        logger.info(
            "Ticket no longer exists in Zammad",
            extra={"handler_stage": "ticket_lookup", "ticket_id": ticket_id},
            exc_info=True,
        )
        raise KafkaPayloadError("Ticket was not found", retryable=False) from e
    except (ZammadRetryableError, ZammadConnectionError) as e:
        logger.error(
            "Error connecting to Zammad",
            extra={"handler_stage": "ticket_lookup", "ticket_id": ticket_id},
            exc_info=True,
        )
        raise KafkaPayloadError("Failed due to Zammad connection error", retryable=True) from e

    original_group_id: int | None = ticket.group_id

    if (
        settings.zammad.type == "eai"
        and settings.zammad.ai_ticket_group_id is not None
        and original_group_id is not None
        and original_group_id != settings.zammad.ai_ticket_group_id
    ):
        try:
            await zammad_client.update_ticket_group(ticket_id=ticket_id, group_id=settings.zammad.ai_ticket_group_id)
            group_state["original_group_id"] = original_group_id
            logger.info(
                "Moved ticket to AI group",
                extra={
                    "handler_stage": "move_to_ai_group",
                    "ticket_id": ticket_id,
                    "target_group_id": settings.zammad.ai_ticket_group_id,
                },
            )
        except (ZammadRetryableError, ZammadConnectionError) as e:
            logger.error(
                "Error connecting to Zammad while moving ticket to AI group",
                extra={
                    "handler_stage": "move_to_ai_group",
                    "ticket_id": ticket_id,
                    "target_group_id": settings.zammad.ai_ticket_group_id,
                },
                exc_info=True,
            )
            raise KafkaPayloadError(
                "Failed due to Zammad connection error while moving ticket to AI group",
                retryable=True,
            ) from e
    else:
        original_group_id = None

    result: TriageResult = await triage_service.perform_triage(ticket=ticket)
    logger.debug(
        "Triage result ready",
        extra={
            "handler_stage": "triage_complete",
            "ticket_id": ticket_id,
            "category": result.category.name,
            "action": result.action.name,
            "confidence": result.confidence,
        },
    )
    await action_service.execute_action(ticket_id=ticket_id, triage=result)


def build_router(settings: ZammadAISettings) -> tuple[KafkaRouter, Callable]:
    """Create and configure a KafkaRouter and its subscriber event handler for ticket triage.

    Parameters:
        settings (ZammadAISettings): Application settings containing Kafka configuration and the set of valid request types.

    Returns:
        tuple[KafkaRouter, Callable]: The configured KafkaRouter and its subscriber event handler.
    """
    logger.info("Building Kafka router")

    # Security setup
    security: BaseSecurity = setup_security(kafka_settings=settings.kafka)

    # Kafka Router
    router = KafkaRouter(
        bootstrap_servers=settings.kafka.broker_url,
        client_id=settings.kafka.client_id,
        logger=logger,
        security=security,
        middlewares=(
            KafkaPrometheusMiddleware(
                registry=REGISTRY,
                app_name="zammad-ai",
                metrics_prefix="zammad_ai_kafka",
            ),
        ),
    )

    triage_service: TriageService = get_triage_service(settings=settings)
    answer_service: AnswerService = get_answer_service(settings=settings)
    action_service: ActionService = get_action_service(settings=settings, answer_service=answer_service)
    broker = router.broker

    @router.subscriber(
        settings.kafka.topic,
        group_id=settings.kafka.group_id,
        ack_policy=AckPolicy.NACK_ON_ERROR,
    )
    async def event_handler(event: Event | dict[str, object]) -> None:
        """Process a Kafka event from the main topic."""
        async with track_activity():
            group_state: dict[str, int | None] = {}
            try:
                await _process_ticket_event(
                    settings=settings,
                    triage_service=triage_service,
                    action_service=action_service,
                    event=event,
                    group_state=group_state,
                )
                original_group_id = group_state.get("original_group_id")
                if original_group_id is not None:
                    ticket_id = (
                        _safe_ticket_id(event.ticket)
                        if isinstance(event, Event)
                        else _safe_ticket_id(event.get("ticket"))
                    )
                    if ticket_id is not None:
                        await _restore_ticket_group(
                            zammad_client=triage_service.zammad_client,
                            ticket_id=ticket_id,
                            group_id=original_group_id,
                            handler_stage="restore_ticket_group",
                            log_message="Moved ticket back to original group",
                        )
            except AckMessage:
                raise
            except Exception as e:
                await _handle_processing_exception(
                    e,
                    ticket_id=_safe_ticket_id(event.ticket)
                    if isinstance(event, Event)
                    else _safe_ticket_id(event.get("ticket")),
                    category_wrong_retry_confidence_threshold=settings.triage.category_wrong_retry_confidence_threshold,
                    broker=broker,
                    settings=settings,
                    zammad_client=triage_service.zammad_client,
                    event=Event.model_validate(event) if not isinstance(event, Event) else event,
                    original_group_id=group_state.get("original_group_id"),
                    retry_count=0,
                )
            raise AckMessage()

    @router.subscriber(
        settings.kafka.retry_topic,
        group_id=settings.kafka.group_id,
        ack_policy=AckPolicy.NACK_ON_ERROR,
    )
    async def retry_event_handler(
        event: Event | dict[str, object],
        retry_after: object | None = Context("message.headers.retry_after"),
        original_group_id: object | None = Context("message.headers.original_group_id"),
        retry_count: object | None = Context("message.headers.retry_count"),
    ) -> None:
        """Process retryable Kafka events after waiting for their retry window."""
        async with track_activity():
            group_state: dict[str, int | None] = {}
            parsed_retry_count = _parse_retry_count(retry_count)
            parsed_original_group_id = _parse_original_group_id(original_group_id)
            remaining_delay_seconds = await _sleep_until_retry_after(
                retry_after,
                retry_delay_seconds=settings.kafka.retry_delay_seconds,
            )
            if remaining_delay_seconds is not None:
                await _reschedule_retry_event(
                    broker=broker,
                    settings=settings,
                    event=event,
                    original_group_id=parsed_original_group_id,
                    retry_count=parsed_retry_count,
                    remaining_delay_seconds=remaining_delay_seconds,
                )
                raise AckMessage()
            try:
                await _process_ticket_event(
                    settings=settings,
                    triage_service=triage_service,
                    action_service=action_service,
                    event=event,
                    group_state=group_state,
                )
                if parsed_original_group_id is None:
                    parsed_original_group_id = group_state.get("original_group_id")
                if parsed_original_group_id is not None:
                    ticket_id = (
                        _safe_ticket_id(event.ticket)
                        if isinstance(event, Event)
                        else _safe_ticket_id(event.get("ticket"))
                    )
                    if ticket_id is not None:
                        await _restore_ticket_group(
                            zammad_client=triage_service.zammad_client,
                            ticket_id=ticket_id,
                            group_id=parsed_original_group_id,
                            handler_stage="restore_ticket_group",
                            log_message="Moved ticket back to original group",
                        )
            except AckMessage:
                raise
            except Exception as e:
                parsed_original_group_id = _parse_original_group_id(original_group_id)
                if parsed_original_group_id is None:
                    parsed_original_group_id = group_state.get("original_group_id")
                await _handle_processing_exception(
                    e,
                    ticket_id=_safe_ticket_id(event.ticket)
                    if isinstance(event, Event)
                    else _safe_ticket_id(event.get("ticket")),
                    category_wrong_retry_confidence_threshold=settings.triage.category_wrong_retry_confidence_threshold,
                    broker=broker,
                    settings=settings,
                    zammad_client=triage_service.zammad_client,
                    event=Event.model_validate(event) if not isinstance(event, Event) else event,
                    original_group_id=parsed_original_group_id,
                    retry_count=parsed_retry_count,
                )
            raise AckMessage()

    return router, event_handler
