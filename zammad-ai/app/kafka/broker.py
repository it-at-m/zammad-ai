"""Kafka router setup for Zammad AI ticket events."""

from collections.abc import Callable
from logging import Logger

from faststream import AckPolicy
from faststream.exceptions import AckMessage, NackMessage
from faststream.kafka.fastapi import KafkaRouter
from faststream.kafka.prometheus import KafkaPrometheusMiddleware
from faststream.security import BaseSecurity
from prometheus_client import REGISTRY

from app.action.service import ActionService, get_action_service
from app.answer.service import AnswerService, get_answer_service
from app.models.kafka import Event
from app.models.triage import TriageResult
from app.settings import ZammadAISettings
from app.triage.triage import TriageService, get_triage_service
from app.utils.logging import getLogger
from app.utils.status import track_activity

from .security import setup_security

logger: Logger = getLogger(name="zammad-ai.kafka.broker")


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
        event: Event,
    ) -> None:
        """Process a Kafka event by performing ticket triage and acknowledging or negatively acknowledging the message.

        Raises:
            AckMessage: If the event is successfully processed or intentionally skipped due to unsupported request type.
            NackMessage: If processing fails.
        """
        async with track_activity():
            logger.debug(f"Received event: {event}")

            # Filter here because information from body is needed
            if event.request_type not in settings.valid_request_types:
                logger.info(f"Skipping event with request type: {event.request_type}")
                raise AckMessage()

            if False:  # TODO: Replace with error handlers
                raise NackMessage()
            try:
                ticket_id: int = int(event.ticket)
                result: TriageResult = await triage_service.perform_triage(id=ticket_id)
                logger.debug(
                    f"Triage result for ticket {ticket_id}: category: {result.category.name}, action: {result.action.name}"
                )
                await action_service.execute_action(ticket_id=ticket_id, triage=result)
            except Exception:
                logger.error(f"Error processing event for ticket {event.ticket}.", exc_info=True)
                raise NackMessage()
            raise AckMessage()

    return router, event_handler
