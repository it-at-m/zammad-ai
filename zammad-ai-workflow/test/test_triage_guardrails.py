"""Tests for guardrail mapping inside the triage service."""

import pytest

import app.triage.triage as triage_module
from app.errors import GuardrailEvaluationError
from app.settings.guardrails import GuardrailSettings
from app.triage.triage import TriageError, TriageService


class _DummyZammadClient:
    def __init__(self, settings) -> None:
        self.settings = settings

    async def close(self) -> None:
        return None


class _DummyPreparserService:
    def preparse(self, message: str) -> str:
        return message


class _DummyGenAIHandler:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def categorize_ticket(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("categorize_ticket should not be called in these tests")


class _GuardrailStub:
    def __init__(
        self,
        settings: GuardrailSettings,
        *,
        evaluate_result: bool = True,
        evaluate_exc: Exception | None = None,
    ) -> None:
        self.settings = settings
        self._evaluate_result = evaluate_result
        self._evaluate_exc = evaluate_exc

    async def evaluate(self, *args, **kwargs) -> bool:
        del args, kwargs
        if self._evaluate_exc is not None:
            raise self._evaluate_exc
        return self._evaluate_result

    async def evaluate_response(self, *args, **kwargs) -> bool:
        del args, kwargs
        return True

    async def close(self) -> None:
        return None


def _build_triage_service(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory,
    guardrail_service: _GuardrailStub,
) -> TriageService:
    monkeypatch.setattr(triage_module, "GenAIHandler", _DummyGenAIHandler)
    monkeypatch.setattr(triage_module, "ZammadAPIClient", _DummyZammadClient)
    monkeypatch.setattr(triage_module, "get_preparser_service", lambda *args, **kwargs: _DummyPreparserService())
    monkeypatch.setattr(triage_module, "get_guardrail_service", lambda settings: guardrail_service)
    settings = settings_factory(guardrails=guardrail_service.settings)
    return TriageService(settings=settings)


@pytest.mark.asyncio
async def test_predict_category_rejects_unsafe_input(monkeypatch: pytest.MonkeyPatch, settings_factory) -> None:
    """Unsafe input should raise a non-retryable triage error."""
    guardrail_service = _GuardrailStub(
        GuardrailSettings(enabled=True, block_on_high_risk=True),
        evaluate_result=False,
    )
    service = _build_triage_service(monkeypatch, settings_factory, guardrail_service)

    with pytest.raises(TriageError) as exc_info:
        await service.predict_category(message="x", session_id="session-id")

    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_predict_category_retries_on_guardrail_failure(
    monkeypatch: pytest.MonkeyPatch, settings_factory
) -> None:
    """Guardrail evaluation failures should be retryable."""
    guardrail_service = _GuardrailStub(
        GuardrailSettings(enabled=True, block_on_high_risk=True),
        evaluate_exc=GuardrailEvaluationError("failed"),
    )
    service = _build_triage_service(monkeypatch, settings_factory, guardrail_service)

    with pytest.raises(TriageError) as exc_info:
        await service.predict_category(message="x", session_id="session-id")

    assert exc_info.value.retryable is True
