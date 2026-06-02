"""Kafka router setup for Zammad AI ticket events."""

from collections.abc import Callable
from logging import Logger

from faststream import AckPolicy
from faststream.exceptions import AckMessage, NackMessage
from faststream.kafka.fastapi import KafkaRouter
from faststream.kafka.prometheus import KafkaPrometheusMiddleware
from faststream.security import BaseSecurity
from prometheus_client import REGISTRY
from pydantic import ValidationError

from app.action.service import ActionService, get_action_service
from app.answer.service import AnswerService, get_answer_service
from app.errors import AckDecision, ExceptionDecision, KafkaPayloadError, classify_exception
from app.models.kafka import Event
from app.models.triage import TriageResult
from app.settings import ZammadAISettings
from app.triage.triage import TriageService, get_triage_service
from app.utils.logging import getLogger
from app.utils.status import track_activity

from .security import setup_security

logger: Logger = getLogger(name="zammad-ai.kafka.broker")


def _handle_processing_exception(
    error: Exception,
    ticket: object,
    category_wrong_retry_confidence_threshold: float,
) -> None:
    """Classify processing errors and raise the corresponding ack/nack signal."""
    decision: ExceptionDecision = classify_exception(
        error,
        category_wrong_retry_confidence_threshold=category_wrong_retry_confidence_threshold,
    )
    logger.error(
        f"Kafka event decision={decision.decision} reason={decision.reason} error_class={decision.error_class} ticket={ticket} caught_class={type(error).__name__}",
        exc_info=True,
    )
    if decision.decision == AckDecision.NACK_RETRY:
        raise NackMessage()
    raise AckMessage()


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

    @router.subscriber(
        settings.kafka.topic,
        group_id=settings.kafka.group_id,
        ack_policy=AckPolicy.NACK_ON_ERROR,
    )
    async def event_handler(
        event: dict[str, object],
    ) -> None:
        """Process a Kafka event by performing ticket triage and acknowledging or negatively acknowledging the message.

        Raises:
            AckMessage: If the event is successfully processed or intentionally skipped due to unsupported request type.
            NackMessage: If processing fails.
        """
        async with track_activity():
            logger.debug(f"Received event: {event}")

            # Parse and validate the incoming event
            try:
                parsed_event: Event = Event.model_validate(event)
            except ValidationError as e:
                logger.error("Failed to parse Kafka event payload", exc_info=True)
                raise AckMessage() from e

            # Skip events with unsupported request types
            if parsed_event.request_type not in settings.kafka.event_processing.valid_request_types:
                logger.info(f"Skipping event with request type: {parsed_event.request_type}")
                raise AckMessage()

            # Skip events with wrong action types
            if parsed_event.action not in settings.kafka.event_processing.valid_action_types:
                logger.info(f"Skipping event with action type: {parsed_event.action}")
                raise AckMessage()

            # Extract ticket ID
            try:
                ticket_id: int = int(parsed_event.ticket)
            except (TypeError, ValueError):
                _handle_processing_exception(
                    KafkaPayloadError("Invalid ticket id in Kafka payload"),
                    ticket=parsed_event.ticket,
                    category_wrong_retry_confidence_threshold=settings.triage.category_wrong_retry_confidence_threshold,
                )

            # Perform triage and execute corresponding actions
            try:
                result: TriageResult = await triage_service.perform_triage(id=ticket_id)
                logger.debug(
                    f"Triage result for ticket {ticket_id}: category: {result.category.name}, action: {result.action.name}"
                )
                await action_service.execute_action(ticket_id=ticket_id, triage=result)
            except Exception as e:
                _handle_processing_exception(
                    e,
                    ticket=parsed_event.ticket,
                    category_wrong_retry_confidence_threshold=settings.triage.category_wrong_retry_confidence_threshold,
                )
            raise AckMessage()

    return router, event_handler
