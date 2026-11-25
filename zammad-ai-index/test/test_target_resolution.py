"""Tests for indexing target resolution and per-target override merging."""

import pytest
from pydantic import ValidationError

from job.settings.settings import ZammadAIIndexSettings, _deep_merge
from job.settings.target import IndexTargetSettings


def test_resolve_targets_requires_at_least_one_target(settings_factory) -> None:
    """An empty target list must be rejected with a descriptive error."""
    settings = settings_factory(targets=[])

    with pytest.raises(ValueError, match="At least one indexing target must be configured"):
        settings.resolve_targets()


def test_resolve_targets_reports_missing_collection_name(settings_factory) -> None:
    """A target without a resolvable collection name must name the missing key."""
    settings = settings_factory(
        qdrant={"collection_name": None},
        targets=[{"name": "kb-only", "zammad": {"knowledge_base_id": 1}}],
    )

    with pytest.raises(ValueError, match="Target 'kb-only' is missing: qdrant.collection_name"):
        settings.resolve_targets()


def test_resolve_targets_reports_missing_knowledge_base_id(settings_factory) -> None:
    """A target without a resolvable knowledge base must name the missing key."""
    settings = settings_factory(
        zammad={"knowledge_base_id": None},
        targets=[{"name": "collection-only", "qdrant": {"collection_name": "c1"}}],
    )

    with pytest.raises(ValueError, match="Target 'collection-only' is missing: zammad.knowledge_base_id"):
        settings.resolve_targets()


def test_resolve_targets_reports_all_missing_fields(settings_factory) -> None:
    """A target missing both required keys must report them together."""
    settings = settings_factory(
        qdrant={"collection_name": None},
        zammad={"knowledge_base_id": None},
        targets=[{"name": "incomplete"}],
    )

    with pytest.raises(
        ValueError, match="Target 'incomplete' is missing: qdrant.collection_name, zammad.knowledge_base_id"
    ):
        settings.resolve_targets()


def test_resolve_targets_resolves_single_target(settings_factory) -> None:
    """A single valid target resolves to its name, effective settings, and laws."""
    settings = settings_factory(
        qdrant={"collection_name": "shared-collection", "timeout": 30},
        zammad={"knowledge_base_id": 1, "category_ids": [1, 2]},
        targets=[{"name": "only"}],
    )

    resolved = settings.resolve_targets()

    assert [target.name for target in resolved] == ["only"]
    effective = resolved[0].settings
    assert effective.qdrant.collection_name == "shared-collection"
    assert effective.qdrant.timeout == 30
    assert effective.zammad.knowledge_base_id == 1
    assert effective.zammad.category_ids == [1, 2]
    assert resolved[0].laws == []


def test_targets_inherit_root_shared_defaults(settings_factory) -> None:
    """Targets inherit root qdrant and zammad values they do not override."""
    settings = settings_factory(
        qdrant={"collection_name": "shared-collection"},
        zammad={"knowledge_base_id": 42},
        targets=[{"name": "only"}],
    )

    resolved = settings.resolve_targets()

    assert resolved[0].settings.qdrant.collection_name == "shared-collection"
    assert resolved[0].settings.zammad.knowledge_base_id == 42


def test_target_overrides_root_qdrant_and_zammad_fields(settings_factory) -> None:
    """Per-target overrides win over root values without affecting other targets."""
    targets = [
        {
            "name": "a",
            "qdrant": {"collection_name": "c-a", "timeout": 99},
            "zammad": {"knowledge_base_id": 1, "category_ids": [7]},
        },
        {"name": "b", "qdrant": {"collection_name": "c-b"}, "zammad": {"knowledge_base_id": 2}},
    ]
    settings = settings_factory(qdrant={"timeout": 30}, targets=targets)

    resolved_a, resolved_b = settings.resolve_targets()

    assert resolved_a.settings.qdrant.timeout == 99
    assert resolved_a.settings.zammad.category_ids == [7]
    assert resolved_b.settings.qdrant.timeout == 30
    assert resolved_b.settings.zammad.category_ids == []


def test_target_overrides_do_not_leak_between_targets(settings_factory) -> None:
    """Each target resolves from the root configuration, not from a previous target."""
    targets = [
        {
            "name": "a",
            "qdrant": {"collection_name": "c-a", "vector_name": "ns-a"},
            "zammad": {"knowledge_base_id": 1},
        },
        {"name": "b", "qdrant": {"collection_name": "c-b"}, "zammad": {"knowledge_base_id": 2}},
    ]
    settings = settings_factory(targets=targets)

    resolved_a, resolved_b = settings.resolve_targets()

    assert resolved_a.settings.qdrant.vector_name == "ns-a"
    assert resolved_b.settings.qdrant.vector_name == ""


def test_target_deep_merges_nested_zammad_overrides(settings_factory) -> None:
    """Nested overrides merge recursively instead of replacing the whole subtree."""
    settings = settings_factory(
        zammad={
            "knowledge_base_id": 1,
            "document_parsing": {"mode": "off", "document_types": ["pdf"]},
        },
        targets=[
            {
                "name": "parser",
                "qdrant": {"collection_name": "c1"},
                "zammad": {"document_parsing": {"mode": "local"}},
            }
        ],
    )

    effective = settings.resolve_targets()[0].settings

    assert effective.zammad.document_parsing.mode == "local"
    assert effective.zammad.document_parsing.document_types == ["pdf"]


def test_resolve_targets_does_not_mutate_root_settings(settings_factory) -> None:
    """Resolving targets must leave the root settings and target dicts untouched."""
    settings = settings_factory(
        targets=[{"name": "t", "qdrant": {"collection_name": "c1"}, "zammad": {"knowledge_base_id": 1}}]
    )

    assert settings.qdrant.collection_name is None
    settings.resolve_targets()

    assert settings.qdrant.collection_name is None
    assert settings.targets[0].qdrant == {"collection_name": "c1"}


def test_resolve_targets_supports_eai_zammad_settings(settings_factory) -> None:
    """Target resolution works for EAI-based Zammad configurations."""
    settings = settings_factory(
        zammad={
            "type": "eai",
            "eai_url": "https://eai.example.com/api/v1",
            "oauth2_client_id": "client-id",
            "oauth2_client_secret": "client-secret",
            "oauth2_token_url": "https://eai.example.com/oauth/token",
            "knowledge_base_id": 5,
        },
        targets=[{"name": "t", "qdrant": {"collection_name": "c1"}}],
    )

    resolved = settings.resolve_targets()

    assert resolved[0].settings.zammad.type == "eai"
    assert resolved[0].settings.zammad.knowledge_base_id == 5


def test_duplicate_target_names_are_rejected(settings_factory) -> None:
    """Two targets sharing a name must fail settings validation."""
    targets = [
        {"name": "dup", "qdrant": {"collection_name": "c1"}, "zammad": {"knowledge_base_id": 1}},
        {"name": "dup", "qdrant": {"collection_name": "c2"}, "zammad": {"knowledge_base_id": 2}},
    ]

    with pytest.raises(ValidationError, match="Duplicate target names in settings: dup"):
        settings_factory(targets=targets)


def test_resolve_targets_rejects_duplicate_collection_names(settings_factory) -> None:
    """Two targets resolving to the same Qdrant collection must be rejected."""
    targets = [
        {"name": "one", "qdrant": {"collection_name": "shared"}, "zammad": {"knowledge_base_id": 1}},
        {"name": "two", "qdrant": {"collection_name": "shared"}, "zammad": {"knowledge_base_id": 2}},
    ]
    settings = settings_factory(targets=targets)

    with pytest.raises(ValueError, match="Targets must resolve to unique Qdrant collections: shared"):
        settings.resolve_targets()


def test_each_target_keeps_its_own_laws(settings_factory) -> None:
    """Laws are scoped per target and carried into each ResolvedTarget."""
    law_a = {"id": "fev", "name": "Fahrerlaubnis-Verordnung", "url": "https://example.com/fev"}
    law_b = {"id": "stvg", "name": "StVG", "url": "https://example.com/stvg"}
    targets = [
        {"name": "a", "qdrant": {"collection_name": "c-a"}, "zammad": {"knowledge_base_id": 1}, "laws": [law_a]},
        {"name": "b", "qdrant": {"collection_name": "c-b"}, "zammad": {"knowledge_base_id": 2}, "laws": [law_b]},
        {"name": "c", "qdrant": {"collection_name": "c-c"}, "zammad": {"knowledge_base_id": 3}},
    ]
    settings = settings_factory(targets=targets)

    resolved = {target.name: target for target in settings.resolve_targets()}

    assert [law.id for law in resolved["a"].laws] == ["fev"]
    assert [law.id for law in resolved["b"].laws] == ["stvg"]
    assert resolved["c"].laws == []


def test_same_law_id_across_targets_is_allowed(settings_factory) -> None:
    """Law ids only need to be unique within a target, not across targets."""
    law = {"id": "fev", "name": "Fahrerlaubnis-Verordnung", "url": "https://example.com/fev"}
    targets = [
        {"name": "a", "qdrant": {"collection_name": "c-a"}, "zammad": {"knowledge_base_id": 1}, "laws": [law]},
        {"name": "b", "qdrant": {"collection_name": "c-b"}, "zammad": {"knowledge_base_id": 2}, "laws": [law]},
    ]
    settings = settings_factory(targets=targets)

    resolved = settings.resolve_targets()

    assert [law.id for law in resolved[0].laws] == ["fev"]
    assert [law.id for law in resolved[1].laws] == ["fev"]


def test_duplicate_law_ids_within_target_are_rejected() -> None:
    """A target with two laws sharing an id must fail settings validation."""
    law = {"id": "fev", "name": "Fahrerlaubnis-Verordnung", "url": "https://example.com/fev"}

    with pytest.raises(ValidationError, match="Duplicate law ids in target 'dup'"):
        IndexTargetSettings(name="dup", qdrant={"collection_name": "c1"}, laws=[law, dict(law)])


def test_root_level_laws_are_ignored(settings_factory) -> None:
    """Laws are only defined per target; a root-level laws key is ignored."""
    settings = settings_factory(
        targets=[{"name": "t", "qdrant": {"collection_name": "c1"}, "zammad": {"knowledge_base_id": 1}}],
        laws=[{"id": "fev", "name": "Fahrerlaubnis-Verordnung", "url": "https://example.com/fev"}],
    )

    resolved = settings.resolve_targets()

    assert resolved[0].laws == []


def test_deep_merge_recursively_merges_nested_dicts() -> None:
    """Nested mappings merge key by key while untouched siblings survive."""
    target: dict = {"a": {"x": 1, "y": 2}, "b": 1}

    _deep_merge(target, {"a": {"y": 3, "z": 4}, "c": 5})

    assert target == {"a": {"x": 1, "y": 3, "z": 4}, "b": 1, "c": 5}


def test_deep_merge_replaces_scalar_with_dict() -> None:
    """A dict override replaces a scalar value at the same key."""
    target: dict = {"a": 1}

    _deep_merge(target, {"a": {"x": 1}})

    assert target == {"a": {"x": 1}}


def test_deep_merge_replaces_dict_with_scalar() -> None:
    """A scalar override replaces a mapping at the same key."""
    target: dict = {"a": {"x": 1}}

    _deep_merge(target, {"a": 5})

    assert target == {"a": 5}


def test_settings_model_exposes_targets_as_index_target_settings(settings_factory) -> None:
    """Target dicts are validated into IndexTargetSettings models on construction."""
    settings = settings_factory(
        targets=[{"name": "t", "qdrant": {"collection_name": "c1"}, "zammad": {"knowledge_base_id": 1}}]
    )

    assert isinstance(settings.targets[0], IndexTargetSettings)
    assert isinstance(settings, ZammadAIIndexSettings)
