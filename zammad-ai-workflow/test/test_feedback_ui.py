"""Tests for the feedback frontend helpers."""

from types import SimpleNamespace
from typing import cast

import gradio as gr
import pytest

from app.frontend.feedback_ui import (
    _load_feedback_trace,
    _load_translations,
    _resolve_feedback_request,
    _submit_feedback,
)
from app.observe.langfuse import LangfuseClient, LangfuseError
from app.utils.token import compute_feedback_token


def _make_request(query_params: dict[str, str], headers: dict[str, str] | None = None) -> gr.Request:
    return cast(
        gr.Request,
        SimpleNamespace(request=SimpleNamespace(query_params=query_params, headers=headers or {})),
    )


@pytest.fixture
def german_translations() -> dict[str, str]:
    """Load the default German feedback frontend translations."""
    return _load_translations("de")


def test_resolve_feedback_request_uses_trace_id_query_param(german_translations: dict[str, str]) -> None:
    """Resolve the trace ID query parameter into feedback request context."""
    request = _make_request({"trace_id": "trace-123", "key": "expected-key"})

    authorized, status, query_params = _resolve_feedback_request(
        request=request,
        expected_access_key="secret-salt",
        translations=german_translations,
    )

    assert authorized is True
    assert status == ""
    assert query_params is not None
    assert query_params.trace_id == "trace-123"
    assert query_params.access_key == "expected-key"


def test_resolve_feedback_request_rejects_blank_query_values(german_translations: dict[str, str]) -> None:
    """Reject blank query parameter values before loading trace data."""
    request = _make_request({"trace_id": "   ", "key": "expected-key"})

    authorized, status, query_params = _resolve_feedback_request(
        request=request,
        expected_access_key="secret-salt",
        translations=german_translations,
    )

    assert authorized is False
    assert status == "Ungültige Bewertung"
    assert query_params is None


def test_load_feedback_trace_validates_query_token(german_translations: dict[str, str]) -> None:
    """Authorize using per-link token from URL and load trace IO."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:  # noqa: D401
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert trace_id == "trace-123"
            assert score_name == "user-thumbs"
            return False

    salt = "secret-salt"
    expected = compute_feedback_token("hello", "world", salt)
    request = _make_request({"trace_id": "trace-123", "key": expected})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf=DummyClient(),
        expected_access_key=salt,
        score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert used_documents == "!!!"
    assert status == "Trace geladen"


def test_load_feedback_trace_hides_io_when_score_exists(german_translations: dict[str, str]) -> None:
    """Do not expose trace content when the requested feedback already exists."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert trace_id == "trace-123"
            assert score_name == "user-thumbs"
            return True

    salt = "secret-salt"
    request = _make_request(
        {
            "trace_id": "trace-123",
            "key": compute_feedback_token("hello", "world", salt),
        }
    )

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf=DummyClient(),
        expected_access_key=salt,
        score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == ""
    assert output_text == ""
    assert used_documents == ""
    assert status == "Bewertung bereits vorhanden"


def test_load_feedback_trace_reports_invalid_trace_id(german_translations: dict[str, str]) -> None:
    """Return a localized error when Langfuse cannot load the trace."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            raise LangfuseError("trace not found")

    request = _make_request({"trace_id": "bad", "key": "expected-key"})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf=DummyClient(),
        expected_access_key="secret-salt",
        score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == ""
    assert output_text == ""
    assert used_documents == ""
    assert status == "Ungültige Trace ID oder Trace nicht gefunden"


def test_load_feedback_trace_returns_load_error_when_score_lookup_fails(
    german_translations: dict[str, str],
) -> None:
    """Fail closed when duplicate-score lookup cannot be completed."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            raise LangfuseError("lookup failed")

    salt = "secret-salt"
    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf=DummyClient(),
        expected_access_key=salt,
        score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == ""
    assert output_text == ""
    assert status == "Fehler beim Laden des Traces"


def test_attach_evaluation_to_trace_records_tags_as_categorical_scores(monkeypatch) -> None:
    """Store each feedback tag as an individual categorical score."""
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
        tags=["outdated information", "wrong tone"],
    )

    assert recorded_calls[0]["name"] == "thumbs"
    assert recorded_calls[0]["trace_id"] == "trace-123"
    assert recorded_calls[0]["metadata"] == {"user": "sachbearbeiter"}
    assert recorded_calls[1] == {
        "name": "tags",
        "value": "outdated information",
        "trace_id": "trace-123",
        "data_type": "CATEGORICAL",
        "metadata": {"user": "sachbearbeiter"},
    }
    assert recorded_calls[2] == {
        "name": "tags",
        "value": "wrong tone",
        "trace_id": "trace-123",
        "data_type": "CATEGORICAL",
        "metadata": {"user": "sachbearbeiter"},
    }


def test_submit_feedback_only_stores_configured_tags(german_translations: dict[str, str]) -> None:
    """Reject tags not included in the configured feedback tag list."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            self.tags: list[str] | None = None
            self.score_name: str | None = None

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

        def attach_evaluation_to_trace(
            self,
            trace_id: str,
            thumbs_up: bool,
            comment: str | None = None,
            user: str | None = None,
            tags: list[str] | None = None,
            score_name: str = "user-thumbs",
        ) -> None:
            self.tags = tags
            self.score_name = score_name

    salt = "secret-salt"
    client = DummyClient()
    result = _submit_feedback(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf=client,
        expected_access_key=salt,
        score_name="configured-thumbs",
        thumbs="down",
        comment="Feedback comment",
        user_name=None,
        tags=["outdated information", "unconfigured"],
        allowed_tags=["outdated information"],
        translations=german_translations,
    )

    assert result == "Bewertung gespeichert"
    assert client.tags == ["outdated information"]
    assert client.score_name == "configured-thumbs"


@pytest.mark.parametrize(
    ("thumbs", "comment", "user_name"),
    [
        ("unexpected", "valid comment", "AB"),
        ("up", "x" * 2_001, "AB"),
        ("up", "valid comment", "x" * 101),
    ],
)
def test_submit_feedback_rejects_invalid_submission(
    thumbs: str,
    comment: str,
    user_name: str,
    german_translations: dict[str, str],
) -> None:
    """Reject invalid browser input without creating a negative score."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            self.evaluation_attached = False

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

        def attach_evaluation_to_trace(
            self,
            trace_id: str,
            thumbs_up: bool,
            comment: str | None = None,
            user: str | None = None,
            tags: list[str] | None = None,
            score_name: str = "thumbs",
        ) -> None:
            self.evaluation_attached = True

    salt = "secret-salt"
    client = DummyClient()
    result = _submit_feedback(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf=client,
        expected_access_key=salt,
        score_name="user-thumbs",
        thumbs=thumbs,
        comment=comment,
        user_name=user_name,
        tags=None,
        allowed_tags=[],
        translations=german_translations,
    )

    assert result == "Ungültige Bewertung"
    assert client.evaluation_attached is False


def test_submit_feedback_returns_save_error_when_score_lookup_fails(
    german_translations: dict[str, str],
) -> None:
    """Do not attach feedback when duplicate-score lookup fails."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            self.evaluation_attached = False

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            raise LangfuseError("lookup failed")

        def attach_evaluation_to_trace(
            self,
            trace_id: str,
            thumbs_up: bool,
            comment: str | None = None,
            user: str | None = None,
            tags: list[str] | None = None,
            score_name: str = "user-thumbs",
        ) -> None:
            self.evaluation_attached = True

    salt = "secret-salt"
    client = DummyClient()
    result = _submit_feedback(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf=client,
        expected_access_key=salt,
        score_name="user-thumbs",
        thumbs="up",
        comment="valid comment",
        user_name="AB",
        tags=None,
        allowed_tags=[],
        translations=german_translations,
    )

    assert result == "Fehler beim Speichern der Bewertung"
    assert client.evaluation_attached is False


def test_submit_feedback_accepts_current_helper_signature(german_translations: dict[str, str]) -> None:
    """Accept valid inputs using the current feedback helper signature."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            self.evaluation_attached = False

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

        def attach_evaluation_to_trace(
            self,
            trace_id: str,
            thumbs_up: bool,
            comment: str | None = None,
            user: str | None = None,
            tags: list[str] | None = None,
            score_name: str = "user-thumbs",
        ) -> None:
            self.evaluation_attached = True

    salt = "secret-salt"
    result = _submit_feedback(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf=DummyClient(),
        expected_access_key=salt,
        score_name="user-thumbs",
        thumbs="up",
        comment="valid comment",
        user_name="AB",
        tags=["outdated information"],
        allowed_tags=["outdated information"],
        translations=german_translations,
    )

    assert result == "Bewertung gespeichert"


def test_load_feedback_trace_uses_english_translations() -> None:
    """Return status messages from the configured English translation catalog."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!"

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

    translations = _load_translations("en")
    salt = "secret-salt"
    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf=DummyClient(),
        expected_access_key=salt,
        score_name="user-thumbs",
        translations=translations,
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert used_documents == "!!!"
    assert status == "Trace loaded"
