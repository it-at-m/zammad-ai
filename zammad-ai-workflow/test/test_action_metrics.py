"""Tests for Kafka business metrics emitted by the action service."""

from collections.abc import Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.action.service import ActionService
from app.errors import GuardrailBlockedError
from app.metrics import KAFKA_TICKET_OUTCOMES_TOTAL
from app.models.answer import NoAnswerPossible, StaticAnswer
from app.models.triage import TriageResult
from app.settings import ZammadAISettings
from app.settings.triage import Action, ActionTypes, Category


class _FakeObservation:
    trace_id = "fresh-trace-id"

    def __enter__(self) -> "_FakeObservation":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def update(self, **_kwargs: object) -> None:
        return None


class _FakeLangfuse:
    def start_as_current_observation(self, **_kwargs: object) -> _FakeObservation:
        return _FakeObservation()


class _FakeLangfuseClient:
    def __init__(self, last_trace_id: str | None) -> None:
        self.langfuse = _FakeLangfuse()
        self.langfuse_handler = MagicMock(last_trace_id=last_trace_id)


def _get_outcome_counter_value(*, category: str, action_type: str, outcome: str) -> float:
    for metric in KAFKA_TICKET_OUTCOMES_TOTAL.collect():
        for sample in metric.samples:
            if sample.name != "zammad_ai_kafka_ticket_outcomes_total":
                continue
            if sample.labels == {"category": category, "action_type": action_type, "outcome": outcome}:
                return sample.value
    return 0.0


def _build_action_service(settings: ZammadAISettings) -> tuple[ActionService, AsyncMock, AsyncMock]:
    service = ActionService.__new__(ActionService)
    service.settings = settings
    service.answer_service = MagicMock()
    service.guardrail_service = MagicMock()
    service.max_user_text_length = settings.max_user_text_length
    service.zammad_client = MagicMock()
    post_answer_mock = AsyncMock()
    post_shared_draft_mock = AsyncMock()
    service.zammad_client.post_answer = post_answer_mock
    service.zammad_client.post_shared_draft = post_shared_draft_mock
    setattr(service, "_post_feedback_internal_note", AsyncMock())
    return service, post_answer_mock, post_shared_draft_mock


@pytest.mark.asyncio
async def test_execute_action_counts_posted_answer_metric(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Posted answers should increment the Kafka answered counter."""
    baseline = _get_outcome_counter_value(category="General", action_type="static_answer", outcome="answer")
    settings = settings_factory()
    service, post_answer_mock, _ = _build_action_service(settings)
    setattr(service, "get_answer", AsyncMock(return_value=StaticAnswer(response="Antwort")))
    triage = TriageResult(
        user_text="Frage",
        category=Category(name="General", auto_publish=True),
        action=Action(name="Static", description="Static", type=ActionTypes.StaticAnswer, answer="Antwort"),
        reasoning="reason",
        confidence=1.0,
    )

    await service.execute_action(ticket_id=1, triage=triage)

    post_answer_mock.assert_awaited_once()
    assert _get_outcome_counter_value(category="General", action_type="static_answer", outcome="answer") == baseline + 1


@pytest.mark.asyncio
async def test_execute_action_counts_posted_shared_draft_metric(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Posted shared drafts should increment the Kafka answered counter."""
    baseline = _get_outcome_counter_value(category="General", action_type="ai_answer", outcome="shared_draft")
    settings = settings_factory()
    settings.frontend.feedback.post_internal_note = False
    service, _, post_shared_draft_mock = _build_action_service(settings)
    setattr(service, "get_answer", AsyncMock(return_value=StaticAnswer(response="Entwurf")))
    triage = TriageResult(
        user_text="Frage",
        category=Category(name="General", auto_publish=False),
        action=Action(name="AI", description="AI", type=ActionTypes.AIAnswer),
        reasoning="reason",
        confidence=1.0,
    )

    await service.execute_action(ticket_id=1, triage=triage)

    post_shared_draft_mock.assert_awaited_once()
    assert (
        _get_outcome_counter_value(category="General", action_type="ai_answer", outcome="shared_draft") == baseline + 1
    )


@pytest.mark.asyncio
async def test_execute_action_posts_feedback_note_for_standard_shared_draft(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Standard answers posted as shared drafts should receive a feedback note."""
    settings = settings_factory()
    settings.frontend.feedback.post_internal_note = True
    service, _, _ = _build_action_service(settings)
    feedback_note_mock = cast(AsyncMock, service._post_feedback_internal_note)
    setattr(service, "get_answer", AsyncMock(return_value=StaticAnswer(response="Standardantwort")))
    triage = TriageResult(
        user_text="Frage",
        category=Category(name="General", auto_publish=False),
        action=Action(name="Standard", description="Standard", type=ActionTypes.StaticAnswer, answer="Antwort"),
        reasoning="reason",
        confidence=1.0,
    )

    await service.execute_action(ticket_id=1, triage=triage)

    feedback_note_mock.assert_awaited_once_with(
        ticket_id=1, user_text="Frage", response=StaticAnswer(response="Standardantwort")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("last_trace_id", [None, "stale-trace-id"])
async def test_execute_action_posts_static_answer_feedback_note_with_fresh_trace(
    settings_factory: Callable[..., ZammadAISettings], last_trace_id: str | None
) -> None:
    """Static answers should use a new trace instead of skipping or reusing feedback links."""
    settings = settings_factory()
    settings.frontend.feedback.post_internal_note = True
    settings.frontend.base_url = "https://example.com"
    service, post_answer_mock, _ = _build_action_service(settings)
    delattr(service, "_post_feedback_internal_note")
    service.answer_service.langfuse_client = _FakeLangfuseClient(last_trace_id)  # ty: ignore
    service.guardrail_service.evaluate = AsyncMock(return_value=True)
    service.guardrail_service.settings = MagicMock(enabled=False, block_on_high_risk=False)
    settings.triage.actions = [
        Action(name="Standard", description="Standard", type=ActionTypes.StaticAnswer, answer="Standardantwort")
    ]

    response = await service.get_answer(
        ticket_id=1,
        category_name="General",
        action_name="Standard",
        user_text="Frage",
        session_id=None,
    )
    assert service.answer_service.langfuse_client.langfuse_handler.last_trace_id == "fresh-trace-id"  # ty: ignore
    await service._post_feedback_internal_note(ticket_id=1, user_text="Frage", response=response)  # ty: ignore

    post_answer_mock.assert_awaited_once()
    assert "trace_id=fresh-trace-id" in post_answer_mock.await_args.kwargs["text"]  # ty: ignore


@pytest.mark.asyncio
async def test_execute_action_reraises_guardrail_block_when_note_post_fails(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """A failed guardrail note must not change the non-retryable block error."""
    settings = settings_factory()
    settings.triage.no_action_internal_note = "Grund: {reason}"
    service, post_answer_mock, _ = _build_action_service(settings)
    post_answer_mock.side_effect = RuntimeError("note failed")
    blocked_error = GuardrailBlockedError("Input failed safety checks")
    setattr(service, "get_answer", AsyncMock(side_effect=blocked_error))
    triage = TriageResult(
        user_text="Frage",
        category=Category(name="General", auto_publish=False),
        action=Action(name="AI", description="AI", type=ActionTypes.AIAnswer),
        reasoning="reason",
        confidence=1.0,
    )

    with pytest.raises(GuardrailBlockedError) as error:
        await service.execute_action(ticket_id=1, triage=triage)

    assert error.value is blocked_error


@pytest.mark.asyncio
async def test_get_answer_does_not_count_manual_metric_for_no_action(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Direct answer generation should not increment the Kafka manual counter."""
    baseline = _get_outcome_counter_value(category="General", action_type="no_action", outcome="manual")
    settings = settings_factory()
    service, _, _ = _build_action_service(settings)
    guardrail_service = cast(Any, service.guardrail_service)
    guardrail_service.evaluate = AsyncMock(return_value=None)
    guardrail_service.settings = MagicMock(enabled=False, block_on_high_risk=False)

    result = await service.get_answer(
        ticket_id=1,
        category_name="General",
        action_name="No Action",
        user_text="Frage",
        session_id=None,
    )

    assert isinstance(result, NoAnswerPossible)
    assert _get_outcome_counter_value(category="General", action_type="no_action", outcome="manual") == baseline


@pytest.mark.asyncio
async def test_execute_action_counts_manual_metric_for_no_action(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Kafka NoAction execution should increment the manual counter."""
    baseline = _get_outcome_counter_value(category="General", action_type="no_action", outcome="manual")
    settings = settings_factory()
    settings.triage.no_action_internal_note = None
    service, _, _ = _build_action_service(settings)
    setattr(
        service,
        "get_answer",
        AsyncMock(
            return_value=NoAnswerPossible(
                reasoning="manual outcome generated by Kafka NoAction execution for a ticket that requires no automated response"
            )
        ),
    )
    triage = TriageResult(
        user_text="Frage",
        category=Category(name="General", auto_publish=False),
        action=Action(name="No Action", description="No Action", type=ActionTypes.NoAction),
        reasoning="reason",
        confidence=1.0,
    )

    await service.execute_action(ticket_id=1, triage=triage)

    assert _get_outcome_counter_value(category="General", action_type="no_action", outcome="manual") == baseline + 1


@pytest.mark.asyncio
async def test_execute_action_posts_no_action_note_for_no_answer_possible(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """NoAnswerPossible should document the no-action result internally."""
    settings = settings_factory()
    settings.triage.no_action_internal_note = "Kategorie: {category}; Aktion: {action}; Grund: {reason}"
    service, post_answer_mock, _ = _build_action_service(settings)
    response = NoAnswerPossible(
        reasoning="Es liegen nicht genug Informationen für eine belastbare Antwort vor, daher kann kein verlässlicher Text erstellt werden."
    )
    setattr(service, "get_answer", AsyncMock(return_value=response))
    triage = TriageResult(
        user_text="Frage",
        category=Category(name="General", auto_publish=False),
        action=Action(name="AI", description="AI", type=ActionTypes.AIAnswer),
        reasoning="reason",
        confidence=1.0,
    )

    await service.execute_action(ticket_id=1, triage=triage)

    post_answer_mock.assert_awaited_once()
    assert post_answer_mock.await_args.kwargs["internal"] is True  # ty: ignore
    assert "No answer possible" in post_answer_mock.await_args.kwargs["text"]  # ty: ignore


@pytest.mark.asyncio
async def test_execute_action_posts_no_action_note_for_guardrail_block(
    settings_factory: Callable[..., ZammadAISettings],
) -> None:
    """Guardrail blocks should document the skipped answer internally."""
    settings = settings_factory()
    settings.triage.no_action_internal_note = "Kategorie: {category}; Aktion: {action}; Grund: {reason}"
    service, post_answer_mock, _ = _build_action_service(settings)
    setattr(service, "get_answer", AsyncMock(side_effect=GuardrailBlockedError("Input failed safety checks")))
    triage = TriageResult(
        user_text="Frage",
        category=Category(name="General", auto_publish=False),
        action=Action(name="AI", description="AI", type=ActionTypes.AIAnswer),
        reasoning="reason",
        confidence=1.0,
    )

    with pytest.raises(GuardrailBlockedError):
        await service.execute_action(ticket_id=1, triage=triage)

    post_answer_mock.assert_awaited_once()
    assert post_answer_mock.await_args.kwargs["internal"] is True  # ty: ignore
    assert "Input failed safety checks" in post_answer_mock.await_args.kwargs["text"]  # ty: ignore
