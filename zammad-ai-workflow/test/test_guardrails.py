"""Tests for the HTTP-based guardrail client service."""
import httpx
import pytest
from pydantic import HttpUrl

from app.guardrails import GuardrailService
from app.models.guardrails import GuardrailResponseResult, GuardrailResult
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
    """When disabled, guardrail client should always return safe without HTTP calls."""
    settings = GuardrailSettings(enabled=False)
    service = GuardrailService(settings)

    result = await service.evaluate("any text")

    assert isinstance(result, GuardrailResult)
    assert result.prompt_safety == "safe"
    assert len(result.prompt_toxicity) == 0
    assert len(result.jailbreak_detection) == 0


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
    """When disabled, response guardrail should always return safe."""
    settings = GuardrailSettings(enabled=False)
    service = GuardrailService(settings)

    result = await service.evaluate_response("prompt", "response")

    assert isinstance(result, GuardrailResponseResult)
    assert result.response_safety == "safe"
    assert len(result.response_toxicity) == 0
    assert len(result.response_refusal) == 0


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

    assert isinstance(result, GuardrailResult)
    assert result.prompt_safety == "unsafe"
    assert "hate_and_discrimination" in result.prompt_toxicity


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

    assert isinstance(result, GuardrailResponseResult)
    assert result.response_safety == "unsafe"
    assert "pii_exposure" in result.response_toxicity


@pytest.mark.asyncio
async def test_guardrail_http_error_fail_open(guardrail_settings: GuardrailSettings) -> None:
    """Client fails open (safe) on HTTP errors."""
    service = GuardrailService(guardrail_settings)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    service._client = httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=2.0)

    result_prompt = await service.evaluate("text")
    result_response = await service.evaluate_response("prompt", "response")

    assert result_prompt.prompt_safety == "safe"
    assert result_response.response_safety == "safe"
