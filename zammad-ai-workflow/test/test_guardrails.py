"""Tests for the guardrail service."""

import pytest
from app.guardrails import GuardrailService
from app.guardrails import service as guardrails_service_module
from app.guardrails.service import get_guardrail_service
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


@pytest.mark.asyncio
async def test_guardrail_service_handles_empty_text(guardrail_service: GuardrailService) -> None:
    """Guardrail service should handle empty or whitespace-only text gracefully."""
    empty_result = await guardrail_service.evaluate("")
    assert isinstance(empty_result, GuardrailResult)
    assert empty_result.prompt_safety == "safe"
    assert len(empty_result.prompt_toxicity) == 0

    whitespace_result = await guardrail_service.evaluate("   \n\t  ")
    assert isinstance(whitespace_result, GuardrailResult)
    assert whitespace_result.prompt_safety == "safe"
    assert len(whitespace_result.prompt_toxicity) == 0


@pytest.mark.asyncio
async def test_guardrail_service_safe_input(guardrail_service: GuardrailService) -> None:
    """Safe input should pass guardrail checks."""
    safe_text = "I would like to request a refund for my recent order. Please help me with this issue."

    result = await guardrail_service.evaluate(safe_text)

    assert isinstance(result, GuardrailResult)
    assert result.prompt_safety == "safe"
    assert hasattr(result, "prompt_toxicity")
    assert hasattr(result, "jailbreak_detection")


@pytest.mark.asyncio
async def test_guardrail_service_evaluates_text(guardrail_service: GuardrailService) -> None:
    """Guardrail service should evaluate text and return a GuardrailResult."""
    text = "This is a test message."

    result = await guardrail_service.evaluate(text)

    assert isinstance(result, GuardrailResult)
    assert hasattr(result, "prompt_safety")
    assert hasattr(result, "prompt_toxicity")
    assert hasattr(result, "jailbreak_detection")
    assert result.prompt_safety in ["safe", "unsafe"]
    assert isinstance(result.prompt_toxicity, list)
    assert isinstance(result.jailbreak_detection, list)


@pytest.mark.asyncio
async def test_guardrail_service_handles_long_text(guardrail_service: GuardrailService) -> None:
    """Guardrail service should truncate text longer than max_length."""
    long_text = "word " * 1000  # Create text longer than max_length

    result = await guardrail_service.evaluate(long_text)

    assert isinstance(result, GuardrailResult)
    assert result.prompt_safety in ["safe", "unsafe"]


def test_guardrail_service_caching() -> None:
    """Guardrail service should cache model instances."""
    settings1 = GuardrailSettings(enabled=True)
    settings2 = GuardrailSettings(enabled=True)

    service1 = get_guardrail_service(settings1)
    service2 = get_guardrail_service(settings2)

    # Same settings should return same instance
    assert service1 is service2


def test_guardrail_service_falls_back_when_model_load_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guardrail service should initialize even if the model cannot be loaded."""
    monkeypatch.setattr(
        guardrails_service_module.GLiNER2,
        "from_pretrained",
        classmethod(lambda cls, *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("load failed"))),
    )

    service = GuardrailService(GuardrailSettings(enabled=True))

    assert service._model is None


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
async def test_guardrail_passes_when_disabled(guardrail_service: GuardrailService) -> None:
    """Guardrail should always pass when disabled, regardless of content."""
    disabled_settings = GuardrailSettings(enabled=False)
    service = GuardrailService(disabled_settings)

    # Evaluate various texts
    test_texts = [
        "Safe content",
        "   ",  # Empty
        "a" * 10000,  # Very long
    ]

    for text in test_texts:
        result = await service.evaluate(text)
        assert isinstance(result, GuardrailResult)
        assert result.prompt_safety == "safe"
        assert len(result.prompt_toxicity) == 0
        assert len(result.jailbreak_detection) == 0


@pytest.mark.asyncio
async def test_guardrail_evaluate_response(guardrail_service: GuardrailService) -> None:
    """Guardrail service should evaluate response text."""
    prompt = "What is the capital of France?"
    response = "Paris is the capital of France."

    result = await guardrail_service.evaluate_response(prompt, response)

    assert isinstance(result, GuardrailResponseResult)
    assert hasattr(result, "response_safety")
    assert hasattr(result, "response_toxicity")
    assert hasattr(result, "response_refusal")
    assert result.response_safety in ["safe", "unsafe"]


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
