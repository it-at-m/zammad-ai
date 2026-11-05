"""Tests for multi-usecase routing and validation."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.models.kafka import Event
from app.models.zammad import ZammadTicket
from app.settings import ZammadAISettings
from app.settings.settings import _resolve_usecases, _validate_usecases
from app.settings.usecase import PollingMatch, RouterSettings, UseCaseMatch, UseCaseSettings
from app.usecases.registry import UseCaseRegistry
from app.usecases.resolver import UseCaseResolver


def test_event_resolver_selects_exact_usecase() -> None:
    """Route an event to its exact request type and action match."""
    resolver = UseCaseResolver(
        [
            UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support", action="created")]),
            UseCaseSettings(name="permits", match=[UseCaseMatch(request_type="permits")]),
        ]
    )

    event = Event(
        action="created",
        ticket="1",
        status="new",
        statusId="1",
        request_type="support",
        lhmExtId=None,
    )

    resolved = resolver.resolve_event(event)
    assert resolved is not None
    assert resolved.name == "support"


def _event(request_type: str) -> Event:
    return Event(
        action="created",
        ticket="1",
        status="new",
        statusId="1",
        request_type=request_type,
        lhmExtId=None,
    )


def test_event_resolver_returns_no_match_when_nothing_is_configured() -> None:
    """A usecase without match rules must keep no-match semantics for every event."""
    resolver = UseCaseResolver([UseCaseSettings(name="default")])

    assert resolver.resolve_event(_event("support")) is None
    assert resolver.resolve_event(_event("anything")) is None


def test_polling_resolver_matches_all_tickets_for_sole_usecase_without_polling_match() -> None:
    """A sole usecase without polling_match rules must accept every polled ticket."""
    usecase = UseCaseSettings(name="default")
    resolver = UseCaseResolver([usecase])

    assert resolver.resolve_ticket(ZammadTicket(id=1, group_name="Any Group")) == usecase


def test_event_resolver_keeps_exact_matching_for_sole_usecase_with_match_rules() -> None:
    """A sole usecase with explicit match rules must not catch unmatched events."""
    resolver = UseCaseResolver([UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")])])

    assert resolver.resolve_event(_event("support")) is not None
    assert resolver.resolve_event(_event("permits")) is None


def test_event_resolver_keeps_unmatched_policy_for_multiple_usecases() -> None:
    """Multiple usecases must keep unmatched-policy handling even when one has no match rules."""
    resolver = UseCaseResolver(
        [
            UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")]),
            UseCaseSettings(name="other"),
        ]
    )

    assert resolver.resolve_event(_event("support")) is not None
    assert resolver.resolve_event(_event("permits")) is None


def test_polling_resolver_uses_ticket_metadata() -> None:
    """Route polling tickets using Zammad group metadata."""
    usecase = UseCaseSettings(name="permits", polling_match=[PollingMatch(group_name="Permits")])
    resolver = UseCaseResolver([usecase])

    assert resolver.resolve_ticket(ZammadTicket(id=1, group_name="Permits")) == usecase
    assert resolver.resolve_ticket(ZammadTicket(id=2, group_name="Support")) is None


def test_overlapping_wildcard_routes_are_rejected() -> None:
    """Reject a broad route that overlaps a more specific route."""
    with pytest.raises(ValueError, match="overlap"):
        _validate_usecases(
            [
                UseCaseSettings(name="all-support", match=[UseCaseMatch(request_type="support")]),
                UseCaseSettings(
                    name="created-support",
                    match=[UseCaseMatch(request_type="support", action="created")],
                ),
            ]
        )


def test_fallback_usecase_must_exist() -> None:
    """Reject a fallback target that is not part of the configured usecases."""
    with pytest.raises(ValueError, match="Fallback usecase"):
        _validate_usecases(
            [UseCaseSettings(name="support")],
            RouterSettings(unmatched_policy="fallback", fallback_usecase="missing"),
        )


def test_fallback_policy_requires_a_target() -> None:
    """Require an explicit target for fallback routing."""
    with pytest.raises(ValueError, match="fallback_usecase"):
        RouterSettings(unmatched_policy="fallback")


def test_registry_preserves_usecase_name_after_config_merge(
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-usecase config must not rename the runtime identity."""
    settings: ZammadAISettings = settings_factory(valid_request_types=["support"])
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings
    definition = UseCaseSettings(
        name="support",
        description="Support",
        config={
            "usecase": {"name": "renamed-by-config"},
            "kafka": {"retry_delay_seconds": 123},
        },
    )
    captured_payload: dict[str, Any] = {}

    def fake_model_validate(payload: dict[str, Any]) -> dict[str, Any]:
        captured_payload.update(payload)
        return payload

    monkeypatch.setattr("app.usecases.registry.ZammadAISettings.model_validate", fake_model_validate)

    registry._build_settings(definition)

    assert captured_payload["usecase"]["name"] == "support"
    assert captured_payload["kafka"]["retry_delay_seconds"] == 123


def test_build_settings_accepts_triage_from_usecase_config(settings_factory) -> None:
    """A usecase may provide triage settings when the root configuration has none."""
    root = settings_factory().model_copy(update={"triage": None}, deep=True)
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = root
    definition = UseCaseSettings(
        name="support",
        config={
            "triage": {
                "categories": [{"name": "General"}],
                "no_category_name": "General",
                "actions": [{"name": "no_action", "description": "No action", "type": "NoAction"}],
                "no_action_name": "no_action",
                "action_rules": [],
                "prompts": {"type": "string", "prompt_map": {"categories": "c", "examples": "e", "role": "r"}},
            }
        },
    )

    effective = registry._build_settings(definition)

    assert effective.triage is not None
    assert effective.triage.no_category_name == "General"


def test_build_settings_requires_triage_when_root_has_none(settings_factory) -> None:
    """Reject usecases without triage settings when the root configuration has none."""
    root = settings_factory().model_copy(update={"triage": None}, deep=True)
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = root

    with pytest.raises(ValueError, match="triage"):
        registry._build_settings(UseCaseSettings(name="support"))


@pytest.mark.asyncio
async def test_registry_cleanup_continues_past_failing_runtimes() -> None:
    """A failing runtime must not prevent the remaining runtimes from being cleaned up."""
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    failing = SimpleNamespace(name="failing", cleanup=AsyncMock(side_effect=RuntimeError("cleanup failed")))
    succeeding = SimpleNamespace(name="succeeding", cleanup=AsyncMock())
    registry.runtimes = cast(dict[str, Any], {"failing": failing, "succeeding": succeeding})

    with pytest.raises(RuntimeError):
        await registry.cleanup()

    failing.cleanup.assert_awaited_once()
    succeeding.cleanup.assert_awaited_once()


def test_registry_warns_when_polling_usecase_has_no_polling_match(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Polling-enabled usecases without polling_match rules must warn at startup."""
    settings: ZammadAISettings = settings_factory(
        usecases=[
            UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")]),
            UseCaseSettings(name="permits", polling_match=[PollingMatch(group_name="Permits")]),
            UseCaseSettings(name="kafka_only", match=[UseCaseMatch(request_type="tax")]),
        ]
    )
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings
    registry.runtimes = cast(
        dict[str, Any],
        {
            "support": SimpleNamespace(settings=SimpleNamespace(polling=SimpleNamespace(enabled=False))),
            "permits": SimpleNamespace(settings=SimpleNamespace(polling=SimpleNamespace(enabled=True))),
            "kafka_only": SimpleNamespace(settings=SimpleNamespace(polling=SimpleNamespace(enabled=True))),
        },
    )

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_inert_polling_usecases()

    assert "Usecase 'kafka_only' has polling enabled but defines no polling_match rules" in caplog.text
    assert "Usecase 'permits'" not in caplog.text
    assert "Usecase 'support'" not in caplog.text


def test_registry_does_not_warn_for_sole_usecase_without_polling_match(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sole usecase matches every polled ticket, so no inert-polling warning is emitted."""
    settings: ZammadAISettings = settings_factory(usecases=[UseCaseSettings(name="default")])
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings
    registry.runtimes = cast(
        dict[str, Any],
        {
            "default": SimpleNamespace(settings=SimpleNamespace(polling=SimpleNamespace(enabled=True))),
        },
    )

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_inert_polling_usecases()

    assert "polling_match" not in caplog.text


def test_registry_warns_for_ruleless_usecase_among_multiple(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A usecase without match and polling_match rules must warn at startup."""
    settings: ZammadAISettings = settings_factory(
        usecases=[
            UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")]),
            UseCaseSettings(name="inert"),
        ]
    )
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_ruleless_usecases()

    assert "Usecase 'inert' defines neither match nor polling_match rules" in caplog.text
    assert "Usecase 'support'" not in caplog.text


def test_registry_does_not_warn_for_fallback_usecase_without_rules(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A ruleless fallback usecase intentionally receives unmatched events, so it must not warn."""
    settings: ZammadAISettings = settings_factory(
        usecases=[
            UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")]),
            UseCaseSettings(name="catchall"),
        ],
        router=RouterSettings(unmatched_policy="fallback", fallback_usecase="catchall"),
    )
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_ruleless_usecases()

    assert "Usecase 'catchall'" not in caplog.text


def test_registry_does_not_warn_for_sole_ruleless_usecase(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sole ruleless usecase matches every polled ticket, so no ruleless warning is emitted."""
    settings: ZammadAISettings = settings_factory(usecases=[UseCaseSettings(name="default")])
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_ruleless_usecases()

    assert "neither match nor polling_match" not in caplog.text


def test_resolve_usecases_keeps_single_usecase_deployments_on_the_legacy_path(settings_factory) -> None:
    """Without usecase files or explicit usecases, deployments must not enter usecase routing.

    Single-usecase deployments keep the legacy path where every Kafka event is
    processed by the root usecase under the shared event-type filters; a
    fallback usecase without match rules would silently drop every event.
    """
    settings: ZammadAISettings = settings_factory()

    assert _resolve_usecases(settings) == []


def test_resolve_usecases_prefers_explicitly_configured_usecases(settings_factory) -> None:
    """Explicitly configured usecases are validated and used as-is."""
    definitions = [UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")])]
    settings: ZammadAISettings = settings_factory(usecases=definitions)

    assert _resolve_usecases(settings) == definitions


def test_resolve_usecases_loads_definition_files(
    settings_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Usecase definition files are loaded and validated when present."""
    settings: ZammadAISettings = settings_factory()
    definitions = [UseCaseSettings(name="permits", match=[UseCaseMatch(request_type="permits")])]
    monkeypatch.setattr("app.settings.settings._load_usecase_definitions", lambda _config_dir: definitions)

    assert _resolve_usecases(settings) == definitions
