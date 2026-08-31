"""Tests for guardrail mapping inside the action service."""

from typing import cast
from unittest.mock import AsyncMock

import pytest

import app.action.service as action_module
from app.errors import ActionExecutionError, GuardrailEvaluationError
from app.guardrails import GuardrailService
from app.models.answer import AnswerCandidate
from app.models.triage import Action
from app.settings.guardrails import GuardrailSettings
from app.settings.triage import ActionTypes


class _DummyZammadClient:
    def __init__(self, settings) -> None:
        self.settings = settings

    async def close(self) -> None:
        return None

    async def post_answer(self, *args, **kwargs) -> None:
        raise AssertionError("post_answer should not be called")

    async def post_shared_draft(self, *args, **kwargs) -> None:
        raise AssertionError("post_shared_draft should not be called")

    async def set_ticket_pending_close(self, *args, **kwargs) -> None:
        raise AssertionError("set_ticket_pending_close should not be called")


class _GuardrailStub:
    def __init__(
        self,
        settings: GuardrailSettings,
        *,
        evaluate_result: bool = True,
        evaluate_response_result: bool = True,
        evaluate_exc: Exception | None = None,
        evaluate_response_exc: Exception | None = None,
    ) -> None:
        self.settings = settings
        self._evaluate_result = evaluate_result
        self._evaluate_response_result = evaluate_response_result
        self._evaluate_exc = evaluate_exc
        self._evaluate_response_exc = evaluate_response_exc

    async def evaluate(self, *args, **kwargs) -> bool:
        del args, kwargs
        if self._evaluate_exc is not None:
            raise self._evaluate_exc
        return self._evaluate_result

    async def evaluate_response(self, *args, **kwargs) -> bool:
        del args, kwargs
        if self._evaluate_response_exc is not None:
            raise self._evaluate_response_exc
        return self._evaluate_response_result

    async def close(self) -> None:
        return None


def _build_action_service(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory,
    guardrail_service: _GuardrailStub,
):
    monkeypatch.setattr(action_module, "ZammadAPIClient", _DummyZammadClient)
    settings = settings_factory(guardrails=guardrail_service.settings)
    ai_action = Action(name="AI Answer", description="AI answer", type=ActionTypes.AIAnswer)
    settings.triage.actions = [*settings.triage.actions, ai_action]
    answer_service = AsyncMock()
    answer_service.generate_answer = AsyncMock(
        return_value=AnswerCandidate(
            subject="S" * 50,
            response="R" * 200,
            documents=[],
        )
    )
    return action_module.ActionService(
        settings=settings,
        answer_service=answer_service,
        guardrail_service=cast(GuardrailService, guardrail_service),
    )


@pytest.mark.asyncio
async def test_get_answer_rejects_unsafe_input(monkeypatch: pytest.MonkeyPatch, settings_factory) -> None:
    """Unsafe user input should raise a non-retryable action error."""
    guardrail_service = _GuardrailStub(
        GuardrailSettings(enabled=True, block_on_high_risk=True),
        evaluate_result=False,
    )
    service = _build_action_service(monkeypatch, settings_factory, guardrail_service)

    with pytest.raises(ActionExecutionError) as exc_info:
        await service.get_answer(
            ticket_id=1,
            category_name="Unknown",
            action_name="AI Answer",
            user_text="x",
            session_id=None,
        )

    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_get_answer_retries_on_input_guardrail_failure(
    monkeypatch: pytest.MonkeyPatch, settings_factory
) -> None:
    """Guardrail evaluation failures before answer generation should be retryable."""
    guardrail_service = _GuardrailStub(
        GuardrailSettings(enabled=True, block_on_high_risk=True),
        evaluate_exc=GuardrailEvaluationError("failed"),
    )
    service = _build_action_service(monkeypatch, settings_factory, guardrail_service)

    with pytest.raises(ActionExecutionError) as exc_info:
        await service.get_answer(
            ticket_id=1,
            category_name="Unknown",
            action_name="AI Answer",
            user_text="x",
            session_id=None,
        )

    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_get_answer_rejects_unsafe_response(monkeypatch: pytest.MonkeyPatch, settings_factory) -> None:
    """Unsafe generated responses should raise a non-retryable action error."""
    guardrail_service = _GuardrailStub(
        GuardrailSettings(enabled=True, block_on_high_risk=True),
        evaluate_result=True,
        evaluate_response_result=False,
    )
    service = _build_action_service(monkeypatch, settings_factory, guardrail_service)

    with pytest.raises(ActionExecutionError) as exc_info:
        await service.get_answer(
            ticket_id=1,
            category_name="Unknown",
            action_name="AI Answer",
            user_text="x",
            session_id=None,
        )

    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_get_answer_retries_on_response_guardrail_failure(
    monkeypatch: pytest.MonkeyPatch, settings_factory
) -> None:
    """Guardrail evaluation failures after answer generation should be retryable."""
    guardrail_service = _GuardrailStub(
        GuardrailSettings(enabled=True, block_on_high_risk=True),
        evaluate_result=True,
        evaluate_response_exc=GuardrailEvaluationError("failed"),
    )
    service = _build_action_service(monkeypatch, settings_factory, guardrail_service)

    with pytest.raises(ActionExecutionError) as exc_info:
        await service.get_answer(
            ticket_id=1,
            category_name="Unknown",
            action_name="AI Answer",
            user_text="x",
            session_id=None,
        )

    assert exc_info.value.retryable is True
