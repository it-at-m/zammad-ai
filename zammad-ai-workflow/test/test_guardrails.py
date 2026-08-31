"""Tests for the HTTP-based guardrail client service."""

import httpx
import pytest
from pydantic import HttpUrl

from app.errors import GuardrailEvaluationError
from app.guardrails import GuardrailService
from app.settings.guardrails import GuardrailSettings


@pytest.fixture
def guardrail_settings() -> GuardrailSettings:
    """Create guardrail settings for testing (enabled and pointing to dummy base_url)."""
    return GuardrailSettings(
        enabled=True,
        confidence_threshold=0.7,
        block_on_high_risk=False,
        base_url=HttpUrl("http://testserver"),
        request_timeout_seconds=2.0,
    )


@pytest.fixture
def guardrail_service(guardrail_settings: GuardrailSettings) -> GuardrailService:
    """Create a guardrail service instance."""
    return GuardrailService(guardrail_settings)


@pytest.mark.asyncio
async def test_guardrail_service_disabled() -> None:
    """When disabled, guardrail client should allow the request through."""
    settings = GuardrailSettings(enabled=False)
    service = GuardrailService(settings)

    result = await service.evaluate("any text")

    assert result is True


def test_guardrail_settings_defaults() -> None:
    """Guardrail settings should have sensible defaults."""
    settings = GuardrailSettings()

    assert settings.enabled is True
    assert settings.confidence_threshold == 0.7
    assert settings.block_on_high_risk is False


@pytest.mark.parametrize("threshold", [0.0, 0.5, 0.9, 1.0])
def test_guardrail_settings_accepts_valid_thresholds(threshold: float) -> None:
    """Guardrail settings should accept valid confidence thresholds."""
    settings = GuardrailSettings(confidence_threshold=threshold)
    assert settings.confidence_threshold == threshold


@pytest.mark.parametrize("invalid_threshold", [-0.1, 1.1])
def test_guardrail_settings_rejects_invalid_thresholds(invalid_threshold: float) -> None:
    """Guardrail settings should reject invalid confidence thresholds."""
    with pytest.raises(ValueError):
        GuardrailSettings(confidence_threshold=invalid_threshold)


def test_guardrail_settings_block_on_high_risk() -> None:
    """Guardrail settings should support block_on_high_risk flag."""
    settings_block = GuardrailSettings(block_on_high_risk=True)
    assert settings_block.block_on_high_risk is True

    settings_warn = GuardrailSettings(block_on_high_risk=False)
    assert settings_warn.block_on_high_risk is False


@pytest.mark.asyncio
async def test_guardrail_response_disabled() -> None:
    """When disabled, response guardrail should allow the response through."""
    settings = GuardrailSettings(enabled=False)
    service = GuardrailService(settings)

    result = await service.evaluate_response("prompt", "response")

    assert result is True


@pytest.mark.asyncio
async def test_guardrail_http_prompt_success(guardrail_settings: GuardrailSettings) -> None:
    """Client returns remote result on successful HTTP call for prompt."""
    service = GuardrailService(guardrail_settings)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/guardrails/prompt"):
            return httpx.Response(
                200,
                json={
                    "prompt_safety": "unsafe",
                    "prompt_toxicity": ["hate_and_discrimination"],
                    "jailbreak_detection": [],
                },
            )
        return httpx.Response(404)

    # Patch internal client to use MockTransport
    transport = httpx.MockTransport(handler)
    service._client = httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=2.0)

    result = await service.evaluate("some text")

    assert result is False


@pytest.mark.asyncio
async def test_guardrail_http_response_success(guardrail_settings: GuardrailSettings) -> None:
    """Client returns remote result on successful HTTP call for response."""
    service = GuardrailService(guardrail_settings)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/guardrails/response"):
            return httpx.Response(
                200,
                json={
                    "response_safety": "unsafe",
                    "response_toxicity": ["pii_exposure"],
                    "response_refusal": [],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    service._client = httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=2.0)

    result = await service.evaluate_response("prompt", "response")

    assert result is False


@pytest.mark.asyncio
async def test_guardrail_http_error_raises_evaluation_error(guardrail_settings: GuardrailSettings) -> None:
    """Client should raise a retryable evaluation error on HTTP failures."""
    service = GuardrailService(guardrail_settings)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    service._client = httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=2.0)

    with pytest.raises(GuardrailEvaluationError):
        await service.evaluate("text")

    with pytest.raises(GuardrailEvaluationError):
        await service.evaluate_response("prompt", "response")


@pytest.mark.asyncio
async def test_guardrail_service_close_is_idempotent(guardrail_settings: GuardrailSettings) -> None:
    """Closing the guardrail service should close the client once and tolerate repeats."""
    service = GuardrailService(guardrail_settings)

    class DummyClient:
        def __init__(self) -> None:
            self.calls = 0

        async def aclose(self) -> None:
            self.calls += 1

    dummy_client = DummyClient()
    service.__dict__["_client"] = dummy_client

    await service.close()
    await service.close()

    assert dummy_client.calls == 1
