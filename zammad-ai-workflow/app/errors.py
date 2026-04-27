"""Shared error taxonomy and Kafka ACK/NACK classification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.utils.logging import getLogger

logger = getLogger("zammad-ai.errors")


@dataclass(slots=True, frozen=True)
class ExceptionDecision:
    """Classification result used by the Kafka broker for ACK/NACK behavior."""

    decision: AckDecision
    reason: str
    error_class: str


class AppError(Exception):
    """Base application exception with retryability metadata for broker policy."""

    retryable: bool = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        """Initialize an application error with optional retryability override."""
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable


class KafkaPayloadError(AppError):
    """Raised when a Kafka event payload is semantically invalid."""

    retryable = False


class TicketNotFoundError(AppError):
    """Raised when the referenced ticket does not exist anymore."""

    retryable = False


class ZammadError(AppError):
    """Base exception for Zammad integration errors."""


class ZammadRetryableError(ZammadError):
    """Transient Zammad failure that should be retried."""

    retryable = True


class ZammadPermanentError(ZammadError):
    """Permanent Zammad failure that should be dropped."""

    retryable = False


class ZammadAuthError(ZammadPermanentError):
    """Zammad authentication/authorization failure."""


class ZammadPayloadParseError(ZammadPermanentError):
    """Raised when Zammad response payload parsing fails."""


class DLFError(AppError):
    """Base exception for DLF integration errors."""


class DLFRetryableError(DLFError):
    """Transient DLF failure that should be retried."""

    retryable = True


class DLFPermanentError(DLFError):
    """Permanent DLF failure that should be dropped."""

    retryable = False


class QdrantError(AppError):
    """Base exception for Qdrant integration errors."""


class QdrantRetryableError(QdrantError):
    """Transient Qdrant failure that should be retried."""

    retryable = True


class QdrantPermanentError(QdrantError):
    """Permanent Qdrant failure that should be dropped."""

    retryable = False


class GenAIError(AppError):
    """Base exception for GenAI provider interactions."""


class GenAITimeoutError(GenAIError):
    """GenAI timeout/transient connectivity issue."""

    retryable = True


class GenAIQuotaError(GenAIError):
    """GenAI rate-limit/quota issue."""

    retryable = True


class GenAIAuthError(GenAIError):
    """GenAI authentication/authorization issue."""

    retryable = False


class GenAIContentFilterError(GenAIError):
    """GenAI content filter rejection."""

    retryable = False


class GenAIModelError(GenAIError):
    """Other model/provider errors."""

    retryable = True


class TriageError(AppError):
    """Base exception for triage orchestration and business logic."""


class TriageCategoryWrongError(TriageError):
    """Raised when category resolution is considered unreliable/wrong."""

    retryable = False

    def __init__(self, message: str, *, confidence: float, retryable: bool | None = None) -> None:
        """Initialize a category mismatch error with model confidence metadata."""
        self.confidence = confidence
        super().__init__(message, retryable=retryable)


class TriageJudgeError(TriageError):
    """Raised for judge-phase failures."""


class AnswerServiceError(AppError):
    """Base exception for answer service orchestration failures."""


class ActionExecutionError(AppError):
    """Raised when action execution fails."""


class AckDecision(Enum):
    """Enum for classifying exceptions into broker ACK/NACK decisions."""

    ACK_DROP = "ack_drop"
    NACK_RETRY = "nack_retry"


def classify_exception(
    error: Exception,
    *,
    category_wrong_retry_confidence_threshold: float,
) -> ExceptionDecision:
    """Classify an exception into broker ACK/NACK behavior."""
    error_class = type(error).__name__

    if isinstance(error, TriageCategoryWrongError):
        retry = error.confidence < category_wrong_retry_confidence_threshold
        return ExceptionDecision(
            decision=AckDecision.NACK_RETRY if retry else AckDecision.ACK_DROP,
            reason="category_wrong_low_confidence" if retry else "category_wrong_high_confidence",
            error_class=error_class,
        )

    if isinstance(error, AppError):
        return ExceptionDecision(
            decision=AckDecision.NACK_RETRY if error.retryable else AckDecision.ACK_DROP,
            reason="typed_retryable_error" if error.retryable else "typed_permanent_error",
            error_class=error_class,
        )

    return ExceptionDecision(
        decision=AckDecision.NACK_RETRY,
        reason="untyped_exception_default_retry",
        error_class=error_class,
    )


def classify_provider_error(error: Exception) -> GenAIError:
    """Map provider/library exceptions to a typed GenAI error class."""
    error_name = f"{type(error).__module__}.{type(error).__name__}".lower()
    message = str(error).lower()
    if "timeout" in error_name or "timeout" in message:
        return GenAITimeoutError("GenAI request timed out")

    if any(token in error_name for token in ("ratelimit", "quota")) or any(
        token in message for token in ("ratelimit", "quota")
    ):
        return GenAIQuotaError("GenAI quota or rate limit reached")

    if any(token in error_name for token in ("authentication", "permission", "unauthorized", "forbidden")) or any(
        token in message for token in ("authentication", "permission", "unauthorized", "forbidden")
    ):
        return GenAIAuthError("GenAI authentication or authorization failed")

    content_filter_tokens = (
        "contentfilter",
        "content_filter",
        "content filter",
        "contentpolicy",
        "content_policy",
        "content policy",
    )
    if any(token in source for token in content_filter_tokens for source in (error_name, message)):
        return GenAIContentFilterError("GenAI content filter rejected request")

    return GenAIModelError("GenAI model invocation failed")
