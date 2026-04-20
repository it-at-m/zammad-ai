"""Unit tests for shared error taxonomy classifiers."""

from app.errors import (
    AckDecision,
    GenAIAuthError,
    GenAIQuotaError,
    TriageCategoryWrongError,
    classify_exception,
    classify_provider_error,
)


def test_classify_exception_retryable_typed_error() -> None:
    """Retryable typed errors should map to NACK retry."""
    decision = classify_exception(
        GenAIQuotaError("rate limited"),
        category_wrong_retry_confidence_threshold=0.5,
    )
    assert decision.decision == AckDecision.NACK_RETRY
    assert decision.error_class == "GenAIQuotaError"


def test_classify_exception_permanent_typed_error() -> None:
    """Permanent typed errors should map to ACK drop."""
    decision = classify_exception(
        GenAIAuthError("auth failed"),
        category_wrong_retry_confidence_threshold=0.5,
    )
    assert decision.decision == AckDecision.ACK_DROP
    assert decision.error_class == "GenAIAuthError"


def test_classify_exception_category_wrong_confidence_threshold() -> None:
    """Category wrong retry decision must depend on configured confidence threshold."""
    retry_decision = classify_exception(
        TriageCategoryWrongError("category wrong", confidence=0.3),
        category_wrong_retry_confidence_threshold=0.6,
    )
    drop_decision = classify_exception(
        TriageCategoryWrongError("category wrong", confidence=0.9),
        category_wrong_retry_confidence_threshold=0.6,
    )

    assert retry_decision.decision == AckDecision.NACK_RETRY
    assert drop_decision.decision == AckDecision.ACK_DROP


def test_classify_provider_error_timeout_and_auth() -> None:
    """Provider error helper should detect timeout and auth failures by class name."""

    class OpenAITimeoutError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    timeout_error = classify_provider_error(OpenAITimeoutError("timeout"))
    auth_error = classify_provider_error(AuthenticationError("auth"))

    assert type(timeout_error).__name__ == "GenAITimeoutError"
    assert type(auth_error).__name__ == "GenAIAuthError"
