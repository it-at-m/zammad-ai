"""Helpers for Kafka message processing."""

import asyncio
import time
from logging import Logger
from typing import Any

from faststream.exceptions import AckMessage, NackMessage

from app.errors import AckDecision, ExceptionDecision, KafkaPayloadError, classify_exception
from app.models.kafka import Event
from app.settings import ZammadAISettings
from app.utils.logging import getLogger
from app.zammad.base import BaseZammadClient, ZammadConnectionError, ZammadRetryableError

logger: Logger = getLogger(name="zammad-ai.kafka.helper")
RETRY_AFTER_HEADER = "retry_after"
RETRY_COUNT_HEADER = "retry_count"
ORIGINAL_GROUP_ID_HEADER = "original_group_id"


def _safe_ticket_id(ticket: Any) -> int | None:
    """Return a ticket id when the value is safely coercible to an integer."""
    try:
        return int(ticket)
    except TypeError, ValueError, OverflowError:
        return None


def _build_retry_headers(retry_after_ms: int, retry_count: int) -> dict[str, str]:
    """Return outgoing retry headers."""
    return {
        RETRY_AFTER_HEADER: str(retry_after_ms),
        RETRY_COUNT_HEADER: str(retry_count),
    }


def _parse_original_group_id(original_group_id: object | None) -> int | None:
    """Extract the original Zammad group id from Kafka headers."""
    if original_group_id is None or not isinstance(original_group_id, (str, bytes, bytearray, int)):
        return None

    try:
        return int(original_group_id)
    except TypeError, ValueError:
        logger.warning(
            "Ignoring invalid original_group_id header",
            extra={"handler_stage": "retry_header_parse_failed", "header_name": ORIGINAL_GROUP_ID_HEADER},
        )
        return None


def _parse_retry_after_ms(retry_after: object | None) -> int | None:
    """Extract a retry-after timestamp in epoch milliseconds from Kafka headers."""
    if retry_after is None:
        return None

    try:
        if not isinstance(retry_after, (str, bytes, bytearray, int)):
            raise TypeError
        return int(retry_after)
    except TypeError, ValueError:
        logger.warning(
            "Ignoring invalid retry_after header",
            extra={"handler_stage": "retry_header_parse_failed", "header_name": RETRY_AFTER_HEADER},
        )
        return None


def _parse_retry_count(retry_count: object | None) -> int:
    """Extract the number of completed retry attempts from Kafka headers."""
    if retry_count is None:
        return 0

    try:
        if not isinstance(retry_count, (str, bytes, bytearray, int)):
            raise TypeError
        return int(retry_count)
    except TypeError, ValueError:
        logger.warning(
            "Ignoring invalid retry_count header",
            extra={"handler_stage": "retry_header_parse_failed", "header_name": RETRY_COUNT_HEADER},
        )
        return 0


async def _sleep_until_retry_after(retry_after: object | None) -> None:
    """Delay retry processing until the retry-after timestamp is reached."""
    retry_after_ms = _parse_retry_after_ms(retry_after)
    if retry_after_ms is None:
        return

    remaining_seconds = (retry_after_ms / 1000) - time.time()
    if remaining_seconds <= 0:
        return

    logger.info(
        "Delaying retry event processing",
        extra={
            "handler_stage": "retry_delay",
            "retry_after_ms": retry_after_ms,
            "sleep_seconds": remaining_seconds,
        },
    )
    await asyncio.sleep(remaining_seconds)


async def _republish_retry_event(
    broker: Any,
    settings: ZammadAISettings,
    event: Event,
    original_group_id: int | None,
    retry_count: int,
) -> None:
    """Republish a failed event to the configured retry topic."""
    next_retry_count = retry_count + 1
    retry_delay_seconds = settings.kafka.retry_delay_seconds * (2**retry_count)
    retry_after_ms = int((time.time() + retry_delay_seconds) * 1000)
    retry_headers = _build_retry_headers(retry_after_ms, next_retry_count)
    if original_group_id is not None:
        retry_headers[ORIGINAL_GROUP_ID_HEADER] = str(original_group_id)
    await broker.publish(
        message=event.model_dump(mode="json"),
        topic=settings.kafka.retry_topic,
        headers=retry_headers,
    )
    logger.info(
        "Republished Kafka event to retry topic",
        extra={
            "handler_stage": "retry_republish",
            "retry_topic": settings.kafka.retry_topic,
            "retry_after_ms": retry_after_ms,
        },
    )


async def _restore_ticket_group(
    *,
    zammad_client: BaseZammadClient,
    ticket_id: int,
    group_id: int,
    handler_stage: str,
    log_message: str,
) -> None:
    """Move a ticket back to its original group."""
    try:
        await zammad_client.update_ticket_group(ticket_id=ticket_id, group_id=group_id)
        logger.info(
            log_message,
            extra={
                "handler_stage": handler_stage,
                "ticket_id": ticket_id,
                "original_group_id": group_id,
            },
        )
    except (ZammadRetryableError, ZammadConnectionError) as e:
        logger.error(
            "Error connecting to Zammad while moving ticket back to original group",
            extra={
                "handler_stage": handler_stage,
                "ticket_id": ticket_id,
                "original_group_id": group_id,
            },
            exc_info=True,
        )
        raise KafkaPayloadError(
            "Failed due to Zammad connection error while moving ticket back to original group",
            retryable=True,
        ) from e


async def _handle_processing_exception(
    error: Exception,
    ticket_id: int | None,
    category_wrong_retry_confidence_threshold: float,
    *,
    broker: Any,
    settings: ZammadAISettings,
    zammad_client: BaseZammadClient,
    event: Event,
    original_group_id: int | None,
    retry_count: int,
) -> None:
    """Classify processing errors and either republish or acknowledge them."""
    decision: ExceptionDecision = classify_exception(
        error,
        category_wrong_retry_confidence_threshold=category_wrong_retry_confidence_threshold,
    )
    logger.error(
        "Kafka event processing failed",
        extra={
            "handler_stage": "exception_classification",
            "ticket_id": ticket_id,
            "decision": decision.decision.value,
            "reason": decision.reason,
            "error_class": decision.error_class,
            "caught_class": type(error).__name__,
        },
        exc_info=True,
    )

    if decision.decision == AckDecision.NACK_RETRY:
        if retry_count >= settings.kafka.max_retry_attempts:
            # Log a warning and restore the ticket group if applicable, then acknowledge the message to prevent further retries.
            logger.warning(
                "Retry limit reached for Kafka event",
                extra={
                    "handler_stage": "retry_limit_reached",
                    "ticket_id": ticket_id,
                    "retry_count": retry_count,
                    "max_retry_attempts": settings.kafka.max_retry_attempts,
                    "retry_topic": settings.kafka.retry_topic,
                },
            )
            if original_group_id is not None:
                restored_ticket_id = ticket_id if ticket_id is not None else _safe_ticket_id(event.ticket)
                if restored_ticket_id is not None:
                    await _restore_ticket_group(
                        zammad_client=zammad_client,
                        ticket_id=restored_ticket_id,
                        group_id=original_group_id,
                        handler_stage="restore_ticket_group",
                        log_message="Moved ticket back to original group",
                    )
            raise AckMessage()

        # Republish the event to the retry topic with updated headers and acknowledge the original message to prevent further processing.
        try:
            await _republish_retry_event(
                broker=broker,
                settings=settings,
                event=event,
                original_group_id=original_group_id,
                retry_count=retry_count,
            )
        except Exception:
            logger.error(
                "Failed to republish Kafka event to retry topic",
                extra={
                    "handler_stage": "retry_republish_failed",
                    "ticket_id": ticket_id,
                    "retry_topic": settings.kafka.retry_topic,
                },
                exc_info=True,
            )
            raise NackMessage()
        raise AckMessage()

    # If the decision is to acknowledge the message without retrying, restore the ticket group if applicable and acknowledge the message.
    if original_group_id is not None:
        restored_ticket_id = ticket_id if ticket_id is not None else _safe_ticket_id(event.ticket)
        if restored_ticket_id is not None:
            await _restore_ticket_group(
                zammad_client=zammad_client,
                ticket_id=restored_ticket_id,
                group_id=original_group_id,
                handler_stage="restore_ticket_group",
                log_message="Moved ticket back to original group",
            )
    raise AckMessage()
