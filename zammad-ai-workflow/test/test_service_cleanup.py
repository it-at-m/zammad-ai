"""Tests for service cleanup and shared guardrail singleton reset."""

from unittest.mock import MagicMock

import pytest

import app.guardrails.http_client as guardrail_module
import app.triage.triage as triage_module
from app.action.service import ActionService
from app.guardrails import GuardrailService, get_guardrail_service
from app.triage.triage import TriageService


class _FailingGuardrailService:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        raise RuntimeError("guardrail close failed")


class _DummyClient:
    def __init__(self, *_args, **_kwargs) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_action_service_cleanup_closes_zammad_and_resets_guardrail_singleton(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory,
) -> None:
    """Action cleanup should close both clients and reset the guardrail singleton."""
    settings = settings_factory()
    answer_service = MagicMock()
    failing_guardrail = _FailingGuardrailService()
    guardrail_module._service = failing_guardrail  # ty: ignore
    monkeypatch.setattr("app.action.service.ZammadAPIClient", _DummyClient)

    service = ActionService(settings=settings, answer_service=answer_service)

    with pytest.raises(RuntimeError, match="guardrail close failed"):
        await service.cleanup()

    assert failing_guardrail.closed is True
    assert getattr(service.zammad_client, "closed") is True
    assert guardrail_module._service is None

    recreated_guardrail = get_guardrail_service(settings=settings.guardrails)
    assert isinstance(recreated_guardrail, GuardrailService)

    await recreated_guardrail.close()
    guardrail_module._service = None


@pytest.mark.asyncio
async def test_triage_service_cleanup_closes_zammad_and_resets_guardrail_singleton(
    monkeypatch: pytest.MonkeyPatch,
    settings_factory,
) -> None:
    """Triage cleanup should close both clients and reset the guardrail singleton."""
    settings = settings_factory()
    failing_guardrail = _FailingGuardrailService()
    guardrail_module._service = failing_guardrail  # ty: ignore
    monkeypatch.setattr(triage_module, "GenAIHandler", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(triage_module, "get_preparser_service", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(triage_module, "ZammadAPIClient", _DummyClient)

    service = TriageService(settings=settings)

    with pytest.raises(RuntimeError, match="guardrail close failed"):
        await service.cleanup()

    assert failing_guardrail.closed is True
    assert getattr(service.zammad_client, "closed") is True
    assert guardrail_module._service is None

    recreated_guardrail = get_guardrail_service(settings=settings.guardrails)
    assert isinstance(recreated_guardrail, GuardrailService)

    await recreated_guardrail.close()
    guardrail_module._service = None
