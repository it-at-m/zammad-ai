"""Tests for the polling-based ticket intake service."""

import asyncio
from collections.abc import Callable
from time import monotonic
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import HttpUrl, SecretStr

import app.polling.service as polling_service_module
from app.errors import (
    TicketAlreadyProcessedError,
    TicketNotFoundError,
    TriageError,
    ZammadPayloadParseError,
)
from app.models.triage import TriageResult
from app.models.zammad import ZammadTicket
from app.polling.service import (
    PollingConfigurationError,
    PollingService,
    get_polling_service,
    reset_polling_service,
)
from app.settings import ZammadAISettings
from app.settings.polling import PollingSettings
from app.settings.triage import Action, ActionTypes, Category
from app.settings.zammad import ZammadAPISettings, ZammadEAISettings
from app.zammad.base import ZammadAuthError, ZammadPermanentError, ZammadRetryableError
from test.fakes import FakeZammadClient


def _triage_result() -> TriageResult:
    """Return a minimal valid TriageResult for polling tests."""
    return TriageResult(
        user_text="x",
        session_id=None,
        category=Category(name="Unknown"),
        reasoning="r",
        confidence=1.0,
        action=Action(name="No Action", description="No action", type=ActionTypes.NoAction),
        extracted_values=None,
    )


def _fake_client(search_results: list[int] | None) -> FakeZammadClient:
    """Create a FakeZammadClient with configured search results."""
    settings = ZammadAPISettings(base_url=HttpUrl("https://example.com"), auth_token=SecretStr("test-token"))
    client = FakeZammadClient(settings=settings)
    client.search_results = search_results
    return client


def _build_service(settings: ZammadAISettings, zammad_client: object) -> tuple[PollingService, AsyncMock, AsyncMock]:
    """Create a PollingService backed by mock triage and action services.

    Parameters:
        settings (ZammadAISettings): Settings containing the polling configuration.
        zammad_client (object): Client exposed via the fake triage service's `zammad_client`.

    Returns:
        tuple[PollingService, AsyncMock, AsyncMock]: The polling service, the `perform_triage`
        mock, and the `execute_action` mock.
    """
    triage_service = MagicMock()
    triage_service.zammad_client = zammad_client
    perform_triage = AsyncMock(return_value=_triage_result())
    triage_service.perform_triage = perform_triage
    action_service = MagicMock()
    execute_action = AsyncMock(return_value=None)
    action_service.execute_action = execute_action
    service = PollingService(settings=settings, triage_service=triage_service, action_service=action_service)
    return service, perform_triage, execute_action


def _make_settings(settings_factory: Callable[..., ZammadAISettings], **polling_overrides: object) -> ZammadAISettings:
    """Create settings with polling enabled and optional polling field overrides."""
    polling_kwargs: dict[str, object] = {
        "enabled": True,
        "interval_seconds": 5,
        "search_query": "state.name:(new)",
        "processed_ttl_seconds": 3600,
        "per_page": 50,
        "max_pages": 1,
    }
    polling_kwargs.update(polling_overrides)
    return settings_factory(polling=PollingSettings(**polling_kwargs))


@pytest.fixture(autouse=True)
def fake_client_is_api_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let FakeZammadClient satisfy the isinstance check in the polling cycle."""
    monkeypatch.setattr(polling_service_module, "ZammadAPIClient", FakeZammadClient)


@pytest.mark.asyncio
async def test_search_and_process_happy_path(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Tickets returned by the search should be triaged, executed, and marked processed."""
    settings = _make_settings(settings_factory)
    service, perform_triage, execute_action = _build_service(settings, _fake_client([1, 2]))

    await service._run_cycle()

    assert perform_triage.await_count == 2
    first_ticket = perform_triage.await_args_list[0].kwargs["ticket"]
    second_ticket = perform_triage.await_args_list[1].kwargs["ticket"]
    assert {first_ticket.id, second_ticket.id} == {1, 2}
    assert execute_action.await_count == 2
    assert execute_action.await_args_list[0].kwargs["ticket_id"] in (1, 2)
    assert isinstance(execute_action.await_args_list[0].kwargs["triage"], TriageResult)
    assert set(service._processed) == {1, 2}


@pytest.mark.asyncio
async def test_dedupe_skips_recently_processed(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Recently processed tickets must not be triaged again in a later cycle."""
    settings = _make_settings(settings_factory, processed_ttl_seconds=3600)
    service, perform_triage, _ = _build_service(settings, _fake_client([1]))

    await service._run_cycle()
    await service._run_cycle()

    assert perform_triage.await_count == 1
    assert set(service._processed) == {1}


@pytest.mark.asyncio
async def test_dedupe_expires_after_ttl(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Deduplication entries older than the TTL must allow reprocessing."""
    settings = _make_settings(settings_factory, processed_ttl_seconds=100)
    service, perform_triage, _ = _build_service(settings, _fake_client([1]))
    service._processed[1] = monotonic() - 101

    await service._run_cycle()

    assert perform_triage.await_count == 1
    assert 1 in service._processed


@pytest.mark.asyncio
async def test_ticket_not_found_does_not_raise(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """A vanished ticket should be skipped without triage and without escaping exceptions."""
    settings = _make_settings(settings_factory)
    client = _fake_client([1])
    client.get_ticket = AsyncMock(side_effect=TicketNotFoundError("gone"))
    service, perform_triage, execute_action = _build_service(settings, client)

    await service._run_cycle()

    perform_triage.assert_not_awaited()
    execute_action.assert_not_awaited()
    assert 1 not in service._processed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lookup_error",
    [
        ZammadAuthError("auth failed"),
        ZammadPermanentError("bad request"),
        ZammadPayloadParseError("unparseable payload"),
    ],
)
async def test_permanent_lookup_error_marks_processed(
    settings_factory: Callable[..., ZammadAISettings], lookup_error: Exception
) -> None:
    """Permanent lookup failures must mark the ticket so later cycles skip it."""
    settings = _make_settings(settings_factory)
    client = _fake_client([1])
    client.get_ticket = AsyncMock(side_effect=lookup_error)
    service, perform_triage, _ = _build_service(settings, client)

    await service._run_cycle()

    perform_triage.assert_not_awaited()
    assert 1 in service._processed

    await service._run_cycle()
    assert client.get_ticket.await_count == 1  # not retried in later cycles


@pytest.mark.asyncio
async def test_retryable_lookup_error_not_marked(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Retryable lookup failures must leave the ticket eligible for a later cycle."""
    settings = _make_settings(settings_factory)
    client = _fake_client([1])
    client.get_ticket = AsyncMock(side_effect=ZammadRetryableError("transient"))
    service, perform_triage, _ = _build_service(settings, client)

    await service._run_cycle()

    assert 1 not in service._processed


@pytest.mark.asyncio
async def test_permanent_error_marks_processed(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Permanent triage failures should mark the ticket and leave it unprocessed in later cycles."""
    settings = _make_settings(settings_factory)
    service, perform_triage, _ = _build_service(settings, _fake_client([1, 2]))

    async def _side_effect(*, ticket: ZammadTicket) -> TriageResult:
        if ticket.id == 1:
            raise TriageError("permanent", retryable=False)
        return _triage_result()

    perform_triage.side_effect = _side_effect

    await service._run_cycle()
    assert 1 in service._processed
    assert 2 in service._processed

    await service._run_cycle()
    assert perform_triage.await_count == 2  # ticket 1 not retried, ticket 2 skipped via dedupe


@pytest.mark.asyncio
async def test_retryable_error_not_marked_for_retry(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Retryable triage failures must not mark the ticket as processed."""
    settings = _make_settings(settings_factory)
    service, perform_triage, _ = _build_service(settings, _fake_client([1]))
    perform_triage.side_effect = TriageError("retryable", retryable=True)

    await service._run_cycle()

    assert 1 not in service._processed


@pytest.mark.asyncio
async def test_one_ticket_failure_does_not_block_others(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """A retryable failure on one ticket must not prevent processing the next ticket."""
    settings = _make_settings(settings_factory)
    client = _fake_client([1, 2])
    service, perform_triage, execute_action = _build_service(settings, client)

    async def _side_effect(*, ticket: ZammadTicket) -> TriageResult:
        if ticket.id == 1:
            raise TriageError("retryable", retryable=True)
        return _triage_result()

    perform_triage.side_effect = _side_effect

    await service._run_cycle()

    assert perform_triage.await_count == 2
    assert execute_action.await_count == 1
    assert 1 not in service._processed
    assert 2 in service._processed


@pytest.mark.asyncio
async def test_already_processed_ticket_skipped(
    monkeypatch: pytest.MonkeyPatch, settings_factory: Callable[..., ZammadAISettings]
) -> None:
    """Tickets that look already processed must be skipped and marked in the dedupe dict."""

    def _raise_already_processed(*_args: object, **_kwargs: object) -> None:
        raise TicketAlreadyProcessedError("already processed")

    monkeypatch.setattr(polling_service_module, "ensure_ticket_not_already_processed", _raise_already_processed)
    settings = _make_settings(settings_factory)
    service, perform_triage, _ = _build_service(settings, _fake_client([1]))

    await service._run_cycle()

    assert 1 in service._processed
    perform_triage.assert_not_awaited()

    await service._run_cycle()
    perform_triage.assert_not_awaited()


@pytest.mark.asyncio
async def test_pagination_stops_on_short_page(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """A short first page must stop pagination after a single request."""
    settings = _make_settings(settings_factory, max_pages=2)
    client = _fake_client([1, 2])
    service, _, _ = _build_service(settings, client)

    await service._run_cycle()

    assert len(client.search_calls) == 1
    assert client.search_calls[0] == {"query": "state.name:(new)", "page": 1, "per_page": 50}


@pytest.mark.asyncio
async def test_pagination_fetches_next_page_on_full_page(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """A full first page must trigger a second page request up to max_pages."""
    settings = _make_settings(settings_factory, per_page=2, max_pages=2)
    client = _fake_client([1, 2])
    client.search_tickets = AsyncMock(side_effect=[[1, 2], [3]])
    service, perform_triage, _ = _build_service(settings, client)

    await service._run_cycle()

    assert client.search_tickets.await_count == 2
    assert [call.kwargs["page"] for call in client.search_tickets.await_args_list] == [1, 2]
    assert perform_triage.await_count == 3
    assert {call.kwargs["ticket"].id for call in perform_triage.await_args_list} == {1, 2, 3}


@pytest.mark.asyncio
async def test_eai_client_rejected(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Polling must refuse construction when configured for the EAI client."""
    eai_settings = ZammadEAISettings(
        base_url=HttpUrl("https://example.com"),
        eai_url=HttpUrl("https://example.com/api/v1"),
        oauth2_client_id="x",
        oauth2_client_secret=SecretStr("s"),
        oauth2_token_url=HttpUrl("https://example.com/oauth/token"),
    )
    settings = settings_factory(zammad=eai_settings)
    with pytest.raises(PollingConfigurationError):
        PollingService(settings=settings, triage_service=MagicMock(), action_service=MagicMock())


@pytest.mark.asyncio
async def test_polling_requires_api_client(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """Polling cycles must fail fast when the triage service lacks the API client."""
    settings = _make_settings(settings_factory)
    service, _, _ = _build_service(settings, MagicMock())

    with pytest.raises(PollingConfigurationError):
        await service._run_cycle()


@pytest.mark.asyncio
async def test_start_runs_cycle_and_stop_cancels_task(settings_factory: Callable[..., ZammadAISettings]) -> None:
    """start() should create the polling task and stop() must cancel it cleanly."""
    settings = _make_settings(settings_factory, interval_seconds=1)
    service, perform_triage, _ = _build_service(settings, _fake_client([1]))

    service.start()
    task = service._task
    assert task is not None
    await asyncio.sleep(0)
    assert not task.done()
    await service.stop()

    assert service._task is None
    assert task.cancelled() or task.done()
    perform_triage.assert_not_awaited()


def test_singleton_get_and_reset() -> None:
    """The module-level polling service should behave as a resettable singleton."""
    reset_polling_service()
    first = get_polling_service(settings=MagicMock(), triage_service=MagicMock(), action_service=MagicMock())
    second = get_polling_service(settings=MagicMock(), triage_service=MagicMock(), action_service=MagicMock())
    try:
        assert first is second
    finally:
        reset_polling_service()

    assert polling_service_module._service is None
