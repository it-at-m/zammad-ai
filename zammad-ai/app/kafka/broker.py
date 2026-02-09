from logging import Logger
from typing import Callable

from faststream import AckPolicy
from faststream.exceptions import AckMessage, NackMessage
from faststream.kafka.fastapi import KafkaRouter
from faststream.security import BaseSecurity

from app.core.context import get_backend_context
from app.core.settings import ZammadAISettings
from app.models.kafka import Event
from app.models.triage import TriageResult
from app.utils.logging import getLogger

from .security import setup_security

logger: Logger = getLogger("zammad-ai")


def build_router(settings: ZammadAISettings) -> tuple[KafkaRouter, Callable]:
    """
    Create a configured KafkaRouter and its subscriber event handler for ticket triage.
    
    Parameters:
        settings (ZammadAISettings): Application settings containing Kafka configuration and valid request types.
    
    Returns:
        tuple[KafkaRouter, Callable]: The configured KafkaRouter and its event handler callable.
    """
    """
    Process a single incoming Kafka event for ticket triage and acknowledge the message.
    
    Parameters:
        event (Event): The incoming Kafka event to process.
    
    Raises:
        AckMessage: Acknowledges the message after processing or when the event is skipped.
        NackMessage: Signals the broker to retry the message when processing should be retried.
    """
    logger.info("Building Kafka router")

    # Security setup
    security: BaseSecurity = setup_security(kafka_settings=settings.kafka)

    # Kafka Router
    router = KafkaRouter(
        bootstrap_servers=settings.kafka.broker_url,
        security=security,
    )

    @router.subscriber(
        settings.kafka.topic,
        group_id=settings.kafka.group_id,
        ack_policy=AckPolicy.NACK_ON_ERROR,
    )
    async def event_handler(
        event: Event,
    ) -> None:
        """
        Process an incoming Kafka event to perform ticket triage and acknowledge the message.
        
        If the event's request type is not supported, the event is acknowledged and skipped. The handler attempts to perform triage for the event's ticket, logs any processing errors, and acknowledges the event when finished.
        
        Args:
            event (Event): The Kafka event to process.
        
        Raises:
            AckMessage: Acknowledges the Kafka message to mark it as processed.
        """
        logger.debug(f"Received event: {event}")

        # Filter here because information from body is needed
        if event.request_type not in settings.valid_request_types:
            logger.info(f"Skipping event with request type: {event.request_type}")
            raise AckMessage()

        if False:  # Replace with error handlers
            raise NackMessage()
        try:
            triage = get_backend_context().triage
            id = event.ticket
            result: TriageResult = await triage.perform_triage(id=id)
            logger.debug(f"Triage result for ticket {id}: {result}")
        except Exception as e:
            logger.error(f"Error processing event for ticket {event.ticket}: {e}")
        raise AckMessage()

    return router, event_handler