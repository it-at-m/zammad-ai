"""Tests for the guardrail service."""

import pytest
from app.guardrails import GuardrailService
from app.models.guardrails import GuardrailResponseResult, GuardrailResult
from app.settings.guardrails import GuardrailSettings


@pytest.fixture
def guardrail_settings() -> GuardrailSettings:
    """Create guardrail settings for testing."""
    return GuardrailSettings(
        enabled=True,
        confidence_threshold=0.7,
        block_on_high_risk=False,
    )


@pytest.fixture(autouse=True)
def mock_guardrail_model(monkeypatch):
    """Mock GLiNER2.from_pretrained, damit kein echtes Modell geladen wird."""
    monkeypatch.setattr(
        "app.guardrails.service.GLiNER2.from_pretrained", classmethod(lambda cls, *_args, **_kwargs: None)
    )


@pytest.fixture
def guardrail_service(guardrail_settings: GuardrailSettings) -> GuardrailService:
    """Create a guardrail service instance."""
    return GuardrailService(guardrail_settings)


@pytest.mark.asyncio
async def test_guardrail_service_disabled() -> None:
    """When disabled, guardrail service should always return safe."""
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
