"""Tests for Langfuse trace tagging in the observe client."""

from typing import cast

from app.observe.langfuse import LangfuseClient


def test_build_config_includes_configured_tags() -> None:
    """Configured tags should be passed as langfuse_tags metadata."""
    client = LangfuseClient(tags=["legal", ""])

    config = cast(dict, client.build_config(session_id="session-id"))

    metadata = cast(dict, config["metadata"])
    assert metadata["langfuse_tags"] == ["legal"]
    assert metadata["langfuse_session_id"] == "session-id"


def test_build_config_omits_tags_when_none_configured() -> None:
    """Without tags the langfuse_tags metadata key should be absent."""
    client = LangfuseClient()

    config = cast(dict, client.build_config(session_id="session-id"))

    metadata = cast(dict, config["metadata"])
    assert "langfuse_tags" not in metadata
    assert metadata["langfuse_session_id"] == "session-id"


def test_build_config_generates_session_id_when_missing() -> None:
    """A missing session id should be generated and tags preserved."""
    client = LangfuseClient(tags=["default"])

    config = cast(dict, client.build_config())

    metadata = cast(dict, config["metadata"])
    assert metadata["langfuse_tags"] == ["default"]
    assert metadata["langfuse_session_id"]
