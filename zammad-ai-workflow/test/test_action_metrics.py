"""Tests for Kafka business metrics emitted by the action service."""

from collections.abc import Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.action.service import ActionService
from app.metrics import KAFKA_TICKET_OUTCOMES_TOTAL
from app.models.answer import NoAnswerPossible, StaticAnswer
from app.models.triage import TriageResult
from app.settings import ZammadAISettings
from app.settings.triage import Action, ActionTypes, Category


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
