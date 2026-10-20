"""Tests for multi-usecase routing and validation."""

import pytest

from app.models.kafka import Event
from app.models.zammad import ZammadTicket
from app.settings.settings import _validate_usecases
from app.settings.usecase import PollingMatch, RouterSettings, UseCaseMatch, UseCaseSettings
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
