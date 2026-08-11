"""Tests for the feedback frontend helpers."""

from types import SimpleNamespace
from typing import cast

import gradio as gr

from app.frontend.feedback_ui import _load_feedback_trace, _resolve_feedback_request
from app.observe.langfuse import LangfuseClient, LangfuseError


def _make_request(query_params: dict[str, str]) -> gr.Request:
    return cast(gr.Request, SimpleNamespace(request=SimpleNamespace(query_params=query_params)))


def test_resolve_feedback_request_uses_query_params() -> None:
    """Resolve query parameters into the expected feedback request values."""
    request = _make_request({"key": "secret-value", "trace_id": "trace-123", "score_name": "custom-score"})

    authorized, status, trace_id, score_name = _resolve_feedback_request(
        request=request,
        expected_access_key="secret-value",
        default_score_name="user-thumbs",
    )

    assert authorized is True
    assert status == ""
    assert trace_id == "trace-123"
    assert score_name == "custom-score"


def test_resolve_feedback_request_rejects_wrong_access_key() -> None:
    """Reject a request when the access key does not match."""
    request = _make_request({"key": "wrong", "trace_id": "trace-123"})

    authorized, status, trace_id, score_name = _resolve_feedback_request(
        request=request,
        expected_access_key="secret-value",
        default_score_name="user-thumbs",
    )

    assert authorized is False
    assert status == "Ungültiger Zugriffsschlüssel"
    assert trace_id == "trace-123"
    assert score_name == "user-thumbs"


def test_load_feedback_trace_reports_invalid_trace_id() -> None:
    """Return a localized error when Langfuse cannot load the trace."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            raise LangfuseError("trace not found")

    request = _make_request({"key": "secret-value", "trace_id": "bad"})

    input_text, output_text, status = _load_feedback_trace(
        request=request,
        lf=DummyClient(),
        expected_access_key="secret-value",
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
