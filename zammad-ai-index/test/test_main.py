"""Tests for the multi-target orchestration behavior of the index job entry point."""

from types import SimpleNamespace
from typing import Any

import pytest

import main
from job.settings.law import LawConfig
from job.settings.settings import ResolvedTarget, ZammadAIIndexSettings


class FakeZammadClient:
    """Zammad client stand-in recording its settings and close() calls."""

    def __init__(self, settings: Any) -> None:
        """Store the settings the client was initialized with."""
        self.settings = settings
        self.closed = False

    def close(self) -> None:
        """Mark the client as closed."""
        self.closed = True


class FakeQdrantClient:
    """Qdrant client stand-in recording snapshots and close() calls."""

    def __init__(self, settings: Any) -> None:
        """Store the settings the client was initialized with."""
        self.settings = settings
        self.closed = False
        self.snapshot_count = 0
        self.snapshot_success = True

    def create_snapshot(self) -> bool:
        """Record a snapshot attempt and report the configured success flag."""
        self.snapshot_count += 1
        return self.snapshot_success

    def close(self) -> None:
        """Mark the client as closed."""
        self.closed = True


@pytest.fixture
def law() -> LawConfig:
    """Provide a minimal law configuration for ingestion tests."""
    return LawConfig(id="fev", name="Fahrerlaubnis-Verordnung", url="https://example.com/fev")


def _resolved_targets(
    settings_factory,
    names: list[str],
    laws_by_name: dict[str, list[LawConfig]] | None = None,
    zammad: dict[str, Any] | None = None,
) -> list[ResolvedTarget]:
    """Resolve one settings object containing the named targets into ResolvedTargets."""
    targets = [
        {
            "name": name,
            "qdrant": {"collection_name": f"collection-{name}"},
            "zammad": {"knowledge_base_id": 1},
            **({"laws": laws_by_name[name]} if laws_by_name and name in laws_by_name else {}),
        }
        for name in names
    ]
    settings: ZammadAIIndexSettings = settings_factory(targets=targets, zammad=zammad)
    return settings.resolve_targets()


def _single_resolved_target(
    settings_factory, *, name: str = "target", laws: list[LawConfig] | None = None, zammad: dict[str, Any] | None = None
) -> ResolvedTarget:
    """Resolve a single-target settings object into its ResolvedTarget."""
    return _resolved_targets(settings_factory, [name], laws_by_name={name: laws} if laws else None, zammad=zammad)[0]


def test_main_continues_after_failed_target_and_reports_failure(monkeypatch, settings_factory) -> None:
    """A failing target must not prevent later targets from running; failures are reported at the end."""
    targets = _resolved_targets(settings_factory, ["broken", "healthy"])
    processed: list[str] = []

    def fake_run_target(target: ResolvedTarget) -> None:
        """Record the target name and fail for the broken target."""
        processed.append(target.name)
        if target.name == "broken":
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "settings", SimpleNamespace(resolve_targets=lambda: targets))
    monkeypatch.setattr(main, "run_target", fake_run_target)

    with pytest.raises(RuntimeError, match="Indexing failed for targets: broken"):
        main.main()

    assert processed == ["broken", "healthy"]


def test_main_completes_without_error_when_all_targets_succeed(monkeypatch, settings_factory) -> None:
    """main() must not raise when every configured target indexes successfully."""
    targets = _resolved_targets(settings_factory, ["one", "two"])
    processed: list[str] = []

    monkeypatch.setattr(main, "settings", SimpleNamespace(resolve_targets=lambda: targets))
    monkeypatch.setattr(main, "run_target", lambda target: processed.append(target.name))

    main.main()

    assert processed == ["one", "two"]


def test_main_reports_every_failed_target(monkeypatch, settings_factory) -> None:
    """main() must list all failing targets in its final error message."""
    targets = _resolved_targets(settings_factory, ["first", "second", "third"])

    def fake_run_target(target: ResolvedTarget) -> None:
        """Fail for every target except the last one."""
        if target.name != "third":
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "settings", SimpleNamespace(resolve_targets=lambda: targets))
    monkeypatch.setattr(main, "run_target", fake_run_target)

    with pytest.raises(RuntimeError, match="Indexing failed for targets: first, second"):
        main.main()


def test_run_target_creates_snapshot_and_ingests_each_law(monkeypatch, settings_factory, law) -> None:
    """Law ingestion must snapshot once, ingest every law, and index with the snapshot flag set."""
    second_law = LawConfig(id="stvg", name="StVG", url="https://example.com/stvg")
    target = _single_resolved_target(settings_factory, name="laws", laws=[law, second_law])

    zammad_clients: list[FakeZammadClient] = []
    qdrant_clients: list[FakeQdrantClient] = []
    ingested: list[str] = []
    indexing_flags: list[bool] = []

    def fake_zammad_client(settings: Any) -> FakeZammadClient:
        """Record and return a fake Zammad client."""
        client = FakeZammadClient(settings)
        zammad_clients.append(client)
        return client

    def fake_qdrant_client(settings: Any) -> FakeQdrantClient:
        """Record and return a fake Qdrant client."""
        client = FakeQdrantClient(settings)
        qdrant_clients.append(client)
        return client

    def fake_ingest_law(law_config: LawConfig, _qdrant_client: FakeQdrantClient) -> None:
        """Record the ingested law id."""
        ingested.append(law_config.id)

    def fake_run_indexing(
        _settings: Any,
        _qdrant_client: FakeQdrantClient,
        _zammad_client: FakeZammadClient,
        *,
        snapshot_already_created: bool,
    ) -> None:
        """Record the snapshot flag passed to the indexing stage."""
        indexing_flags.append(snapshot_already_created)

    monkeypatch.setattr(main, "ZammadAPIClient", fake_zammad_client)
    monkeypatch.setattr(main, "QdrantKBClient", fake_qdrant_client)
    monkeypatch.setattr(main, "ingest_law", fake_ingest_law)
    monkeypatch.setattr(main, "run_indexing", fake_run_indexing)

    main.run_target(target)

    assert qdrant_clients[0].snapshot_count == 1
    assert ingested == ["fev", "stvg"]
    assert indexing_flags == [True]
    assert zammad_clients[0].closed
    assert qdrant_clients[0].closed


def test_run_target_aborts_law_stage_when_snapshot_fails(monkeypatch, settings_factory, law) -> None:
    """A failed pre-law snapshot must abort ingestion and indexing but still clean up."""
    target = _single_resolved_target(settings_factory, name="snapshot-fail", laws=[law])

    zammad_client = FakeZammadClient(target.settings)
    qdrant_client = FakeQdrantClient(target.settings)
    qdrant_client.snapshot_success = False
    ingested: list[str] = []
    indexed: list[bool] = []

    def fake_ingest_law(law_config: LawConfig, _qdrant_client: FakeQdrantClient) -> None:
        """Record the ingested law id."""
        ingested.append(law_config.id)

    def fake_run_indexing(*_args: Any, **_kwargs: Any) -> None:
        """Record that the indexing stage was reached."""
        indexed.append(True)

    monkeypatch.setattr(main, "ZammadAPIClient", lambda _settings: zammad_client)
    monkeypatch.setattr(main, "QdrantKBClient", lambda _settings: qdrant_client)
    monkeypatch.setattr(main, "ingest_law", fake_ingest_law)
    monkeypatch.setattr(main, "run_indexing", fake_run_indexing)

    with pytest.raises(RuntimeError, match="Failed to create Qdrant snapshot before law ingestion"):
        main.run_target(target)

    assert qdrant_client.snapshot_count == 1
    assert ingested == []
    assert indexed == []
    assert zammad_client.closed
    assert qdrant_client.closed


def test_run_target_skips_law_stage_without_laws(monkeypatch, settings_factory) -> None:
    """Targets without laws must index directly and leave snapshotting to run_indexing."""
    target = _single_resolved_target(settings_factory, name="plain")

    zammad_client = FakeZammadClient(target.settings)
    qdrant_client = FakeQdrantClient(target.settings)
    ingested: list[str] = []
    indexing_flags: list[bool] = []

    def fake_ingest_law(_law_config: LawConfig, _qdrant_client: FakeQdrantClient) -> None:
        """Record that law ingestion was reached."""
        ingested.append("called")

    def fake_run_indexing(
        _settings: Any,
        _qdrant_client: FakeQdrantClient,
        _zammad_client: FakeZammadClient,
        *,
        snapshot_already_created: bool,
    ) -> None:
        """Record the snapshot flag passed to the indexing stage."""
        indexing_flags.append(snapshot_already_created)

    monkeypatch.setattr(main, "ZammadAPIClient", lambda _settings: zammad_client)
    monkeypatch.setattr(main, "QdrantKBClient", lambda _settings: qdrant_client)
    monkeypatch.setattr(main, "ingest_law", fake_ingest_law)
    monkeypatch.setattr(main, "run_indexing", fake_run_indexing)

    main.run_target(target)

    assert qdrant_client.snapshot_count == 0
    assert ingested == []
    assert indexing_flags == [False]
    assert zammad_client.closed
    assert qdrant_client.closed


def test_run_target_selects_eai_client_for_eai_settings(monkeypatch, settings_factory) -> None:
    """EAI-configured targets must use the EAI client instead of the API client."""
    eai = {
        "type": "eai",
        "eai_url": "https://eai.example.com/api/v1",
        "oauth2_client_id": "client-id",
        "oauth2_client_secret": "client-secret",
        "oauth2_token_url": "https://eai.example.com/oauth/token",
    }
    target = _single_resolved_target(settings_factory, name="eai", zammad=eai)

    clients: list[str] = []

    def fake_api_client(_settings: Any) -> FakeZammadClient:
        """Record an API client instantiation."""
        clients.append("api")
        return FakeZammadClient(target.settings)

    def fake_eai_client(_settings: Any) -> FakeZammadClient:
        """Record an EAI client instantiation."""
        clients.append("eai")
        return FakeZammadClient(target.settings)

    monkeypatch.setattr(main, "ZammadAPIClient", fake_api_client)
    monkeypatch.setattr(main, "ZammadEAIClient", fake_eai_client)
    monkeypatch.setattr(main, "QdrantKBClient", lambda _settings: FakeQdrantClient(target.settings))
    monkeypatch.setattr(main, "run_indexing", lambda *_args, **_kwargs: None)

    main.run_target(target)

    assert clients == ["eai"]


def test_run_target_cleans_up_when_indexing_fails(monkeypatch, settings_factory) -> None:
    """Failures during indexing must propagate after both clients were closed."""
    target = _single_resolved_target(settings_factory, name="failing")

    zammad_client = FakeZammadClient(target.settings)
    qdrant_client = FakeQdrantClient(target.settings)

    def fake_run_indexing(*_args: Any, **_kwargs: Any) -> None:
        """Simulate a critical indexing failure."""
        raise RuntimeError("indexing exploded")

    monkeypatch.setattr(main, "ZammadAPIClient", lambda _settings: zammad_client)
    monkeypatch.setattr(main, "QdrantKBClient", lambda _settings: qdrant_client)
    monkeypatch.setattr(main, "run_indexing", fake_run_indexing)

    with pytest.raises(RuntimeError, match="indexing exploded"):
        main.run_target(target)

    assert zammad_client.closed
    assert qdrant_client.closed
