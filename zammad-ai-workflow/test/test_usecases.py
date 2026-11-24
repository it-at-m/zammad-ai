"""Tests for multi-usecase routing and validation."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.models.kafka import Event
from app.models.zammad import ZammadTicket
from app.settings import ZammadAISettings
from app.settings.settings import _load_usecase_definitions, _resolve_usecases, _validate_usecases
from app.settings.usecase import PollingMatch, RouterSettings, UseCaseMatch, UseCaseSettings
from app.usecases.registry import UseCaseRegistry
from app.usecases.resolver import UseCaseResolver


def test_event_resolver_selects_exact_usecase() -> None:
    """Route an event to its exact request type and action match."""
    resolver = UseCaseResolver(
        [
            UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support", action="created")]),
            UseCaseSettings(name="example-usecase", match=[UseCaseMatch(request_type="example-request")]),
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
    assert resolver.resolve_event(_event("example-request")) is None


def test_event_resolver_keeps_unmatched_policy_for_multiple_usecases() -> None:
    """Multiple usecases must keep unmatched-policy handling even when one has no match rules."""
    resolver = UseCaseResolver(
        [
            UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")]),
            UseCaseSettings(name="other"),
        ]
    )

    assert resolver.resolve_event(_event("support")) is not None
    assert resolver.resolve_event(_event("example-request")) is None


def test_polling_resolver_uses_ticket_metadata() -> None:
    """Route polling tickets using Zammad group metadata."""
    usecase = UseCaseSettings(name="example-usecase", polling_match=[PollingMatch(group_name="Example Group")])
    resolver = UseCaseResolver([usecase])

    assert resolver.resolve_ticket(ZammadTicket(id=1, group_name="Example Group")) == usecase
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


def test_overlapping_rules_within_one_usecase_are_allowed() -> None:
    """Redundant rules inside one usecase resolve deterministically and must not be rejected."""
    _validate_usecases(
        [
            UseCaseSettings(
                name="support",
                match=[
                    UseCaseMatch(request_type="support"),
                    UseCaseMatch(request_type="support", action="created"),
                ],
            )
        ]
    )


def test_overlapping_polling_rules_within_one_usecase_are_allowed() -> None:
    """Redundant polling rules inside one usecase resolve deterministically and must not be rejected."""
    _validate_usecases(
        [
            UseCaseSettings(
                name="support",
                polling_match=[
                    PollingMatch(group_id=9),
                    PollingMatch(group_id=9, group_name="Support"),
                ],
            )
        ]
    )


def test_validate_usecases_rejects_empty_names() -> None:
    """Empty usecase names must fail startup validation."""
    with pytest.raises(ValueError, match="must not be empty"):
        _validate_usecases([UseCaseSettings(name=""), UseCaseSettings(name="support")])


def test_validate_usecases_rejects_whitespace_names() -> None:
    """Whitespace-only usecase names must fail startup validation."""
    with pytest.raises(ValueError, match="must not be empty"):
        _validate_usecases([UseCaseSettings(name="   ")])


def test_load_usecase_definitions_rejects_falsey_documents(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falsey YAML documents must be rejected instead of silently becoming a default usecase."""
    monkeypatch.setattr("app.settings.settings._is_test_mode", lambda: False)
    (tmp_path / "false.yaml").write_text("false\n", encoding="utf-8")
    (tmp_path / "list.yaml").write_text("- a\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        _load_usecase_definitions(tmp_path)


def test_load_usecase_definitions_rejects_blank_documents(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank YAML documents must be rejected instead of silently becoming a default usecase."""
    monkeypatch.setattr("app.settings.settings._is_test_mode", lambda: False)
    (tmp_path / "empty.yaml").write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML mapping"):
        _load_usecase_definitions(tmp_path)


def test_load_usecase_definitions_loads_valid_documents(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid usecase definition files are loaded in sorted order."""
    monkeypatch.setattr("app.settings.settings._is_test_mode", lambda: False)
    (tmp_path / "support.yaml").write_text("name: support\n", encoding="utf-8")
    (tmp_path / "permits.yaml").write_text("name: permits\n", encoding="utf-8")

    definitions = _load_usecase_definitions(tmp_path)

    assert [definition.name for definition in definitions] == ["permits", "support"]


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
    settings: ZammadAISettings = settings_factory()
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
            UseCaseSettings(name="example-usecase", polling_match=[PollingMatch(group_name="Example Group")]),
            UseCaseSettings(name="kafka_only", match=[UseCaseMatch(request_type="tax")]),
        ]
    )
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings
    registry.runtimes = cast(
        dict[str, Any],
        {
            "support": SimpleNamespace(settings=SimpleNamespace(polling=SimpleNamespace(enabled=False))),
            "example-usecase": SimpleNamespace(settings=SimpleNamespace(polling=SimpleNamespace(enabled=True))),
            "kafka_only": SimpleNamespace(settings=SimpleNamespace(polling=SimpleNamespace(enabled=True))),
        },
    )

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_inert_polling_usecases()

    assert "Usecase 'kafka_only' has polling enabled but defines no polling_match rules" in caplog.text
    assert "Usecase 'example-usecase'" not in caplog.text
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


def test_registry_warns_for_sole_ruleless_usecase_with_skip_policy(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sole ruleless usecase under the default skip policy drops every Kafka event and must warn."""
    settings: ZammadAISettings = settings_factory(usecases=[UseCaseSettings(name="default")])
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_ruleless_usecases()

    assert "Usecase 'default' defines no match rules" in caplog.text
    assert "every Kafka event will be dropped" in caplog.text


def test_registry_does_not_warn_for_sole_ruleless_usecase_with_fallback_policy(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sole ruleless usecase with the fallback policy receives unmatched events, so it must not warn."""
    settings: ZammadAISettings = settings_factory(
        usecases=[UseCaseSettings(name="default")],
        router=RouterSettings(unmatched_policy="fallback", fallback_usecase="default"),
    )
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_ruleless_usecases()

    assert "neither match nor polling_match" not in caplog.text
    assert "every Kafka event will be dropped" not in caplog.text


def test_registry_does_not_warn_for_sole_usecase_with_match_rules(
    settings_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A sole usecase with match rules processes matching Kafka events, so it must not warn."""
    settings: ZammadAISettings = settings_factory(
        usecases=[UseCaseSettings(name="support", match=[UseCaseMatch(request_type="support")])]
    )
    registry = UseCaseRegistry.__new__(UseCaseRegistry)
    registry.root_settings = settings

    with caplog.at_level(logging.WARNING, logger="zammad-ai.usecases.registry"):
        registry._warn_ruleless_usecases()

    assert "neither match nor polling_match" not in caplog.text
    assert "every Kafka event will be dropped" not in caplog.text


def test_validate_usecases_rejects_per_usecase_kafka_override() -> None:
    """Per-usecase kafka overrides must fail validation because retry events could be stranded."""
    usecases = [
        UseCaseSettings(
            name="support",
            match=[UseCaseMatch(request_type="support")],
            config={"kafka": {"retry_topic": "stranded-retry-topic"}},
        ),
    ]

    with pytest.raises(ValueError, match="must not override 'kafka' settings"):
        _validate_usecases(usecases)


def test_validate_usecases_allows_non_kafka_config_overrides() -> None:
    """Per-usecase overrides outside the kafka block must remain valid."""
    usecases = [
        UseCaseSettings(
            name="support",
            match=[UseCaseMatch(request_type="support")],
            config={"triage": {"no_category_name": "Unknown"}},
        ),
    ]

    _validate_usecases(usecases)


def test_resolve_usecases_requires_at_least_one_usecase(settings_factory) -> None:
    """Without explicit usecases or usecase definition files, settings loading must fail."""
    settings: ZammadAISettings = settings_factory(usecases=[])

    with pytest.raises(ValueError, match="At least one usecase"):
        _resolve_usecases(settings)


def test_resolve_usecases_rejects_root_level_usecase(settings_factory) -> None:
    """The root-level `usecase` field is populated internally and must not be configured."""
    settings: ZammadAISettings = settings_factory(usecase=UseCaseSettings(name="default"))

    with pytest.raises(ValueError, match="Root-level 'usecase'"):
        _resolve_usecases(settings)


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
    settings: ZammadAISettings = settings_factory(usecases=[])
    definitions = [UseCaseSettings(name="example-usecase", match=[UseCaseMatch(request_type="example-request")])]
    monkeypatch.setattr("app.settings.settings._load_usecase_definitions", lambda _config_dir: definitions)

    assert _resolve_usecases(settings) == definitions
