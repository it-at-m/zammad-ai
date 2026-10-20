"""Tests for multi-usecase routing and validation."""

from typing import Any

import pytest

from app.models.kafka import Event
from app.models.zammad import ZammadTicket
from app.settings import ZammadAISettings
from app.settings.settings import _validate_usecases
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

    runtime_settings = registry._build_settings(definition)

    assert runtime_settings["usecase"]["name"] == "support"
    assert runtime_settings["kafka"]["retry_delay_seconds"] == 123
    assert captured_payload["usecase"]["name"] == "support"
    assert captured_payload["kafka"]["retry_delay_seconds"] == 123
