"""Tests for the feedback frontend helpers."""

from types import SimpleNamespace
from typing import cast

import gradio as gr

from app.frontend.feedback_ui import _compute_feedback_token, _load_feedback_trace, _resolve_feedback_request
from app.observe.langfuse import LangfuseClient, LangfuseError


def _make_request(query_params: dict[str, str], headers: dict[str, str] | None = None) -> gr.Request:
    return cast(
        gr.Request,
        SimpleNamespace(request=SimpleNamespace(query_params=query_params, headers=headers or {})),
    )


def test_resolve_feedback_request_uses_query_params() -> None:
    """Resolve query parameters into the expected feedback request values (no auth here)."""
    request = _make_request({"trace_id": "trace-123", "score_name": "custom-score"})

    authorized, status, trace_id, score_name = _resolve_feedback_request(
        request=request,
        expected_access_key="secret-salt",
        default_score_name="user-thumbs",
    )

    assert authorized is True
    assert status == ""
    assert trace_id == "trace-123"
    assert score_name == "custom-score"


def test_load_feedback_trace_validates_query_token() -> None:
    """Authorize using per-link token from URL and load trace IO."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:  # noqa: D401
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert trace_id == "trace-123"
            assert score_name == "user-thumbs"
            return False

    salt = "secret-salt"
    expected = _compute_feedback_token("hello", "world", salt)
    request = _make_request({"trace_id": "trace-123", "key": expected})

    input_text, output_text, status = _load_feedback_trace(
        request=request,
        lf=DummyClient(),
        expected_access_key=salt,
        default_score_name="user-thumbs",
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert status == "Trace geladen"


def test_load_feedback_trace_hides_io_when_score_exists() -> None:
    """Do not expose trace content when the requested feedback already exists."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert trace_id == "trace-123"
            assert score_name == "user-thumbs"
            return True

    salt = "secret-salt"
    request = _make_request(
        {
            "trace_id": "trace-123",
            "key": _compute_feedback_token("hello", "world", salt),
        }
    )

    input_text, output_text, status = _load_feedback_trace(
        request=request,
        lf=DummyClient(),
        expected_access_key=salt,
        default_score_name="user-thumbs",
    )

    assert input_text == ""
    assert output_text == ""
    assert status == "Bewertung bereits vorhanden"


def test_load_feedback_trace_reports_invalid_trace_id() -> None:
    """Return a localized error when Langfuse cannot load the trace."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            raise LangfuseError("trace not found")

    request = _make_request({"trace_id": "bad"})

    input_text, output_text, status = _load_feedback_trace(
        request=request,
        lf=DummyClient(),
        expected_access_key="secret-salt",
        default_score_name="user-thumbs",
    )

    assert input_text == ""
    assert output_text == ""
    assert status == "Ungültige Trace ID oder Trace nicht gefunden"


def test_attach_evaluation_to_trace_uses_configurable_score_name(monkeypatch) -> None:
    """Use the configured score name when storing trace feedback."""
    recorded_calls: list[dict[str, object]] = []

    class DummyLangfuse:
        def create_score(self, **kwargs):
            recorded_calls.append(kwargs)

    monkeypatch.setattr("app.observe.langfuse.Langfuse", DummyLangfuse)

    client = LangfuseClient()
    client.attach_evaluation_to_trace(
        trace_id="trace-123",
        thumbs_up=True,
        comment="ok",
        user="sachbearbeiter",
        score_name="feedback-vote",
    )

    assert recorded_calls[0]["name"] == "feedback-vote"
    assert recorded_calls[0]["trace_id"] == "trace-123"
