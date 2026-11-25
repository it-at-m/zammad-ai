"""Tests for the feedback frontend helpers."""

from types import SimpleNamespace
from typing import Any, cast

import gradio as gr
import pytest

from app.frontend.feedback_ui import (
    _load_feedback_trace,
    _load_translations,
    _resolve_access_key,
    _resolve_feedback_request,
    _resolve_score_name,
    _submit_feedback,
    build_feedback_frontend,
)
from app.observe.langfuse import LangfuseClient, LangfuseError
from app.settings import FrontendSettings
from app.settings.frontend import FeedbackSettings
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
        access_key_configured=True,
        translations=german_translations,
    )

    assert authorized is True
    assert status == ""
    assert query_params is not None
    assert query_params.trace_id == "trace-123"
    assert query_params.access_key == "expected-key"


def test_get_trace_io_supports_static_answer_string_output() -> None:
    """Feedback loading should support the raw input/output of static-answer traces."""

    class DummyTraceAPI:
        def get(self, trace_id: str, fields: str) -> dict[str, str]:
            assert trace_id == "static-trace"
            assert fields == "core,io"
            return {"input": "Eine Anfrage", "output": "Eine statische Antwort"}

    client = cast(Any, LangfuseClient.__new__(LangfuseClient))
    setattr(client, "langfuse", SimpleNamespace(api=SimpleNamespace(trace=DummyTraceAPI())))

    input_text, output_text, used_documents, trace_tags = client.get_trace_io(trace_id="static-trace")

    assert input_text == "Eine Anfrage"
    assert output_text == "Eine statische Antwort"
    assert used_documents == ""
    assert trace_tags == []


def test_get_trace_io_supports_nested_answer_output() -> None:
    """Feedback loading should accept Langfuse output wrapped in a response object."""

    class DummyTraceAPI:
        def get(self, trace_id: str, fields: str) -> dict[str, dict[str, object]]:
            assert trace_id == "answer-trace"
            assert fields == "core,io"
            return {
                "input": {"kwargs": {"user_text": "Eine Anfrage"}},
                "output": {
                    "response": {
                        "subject": "Ein sehr langer Antwortbetreff, der die Mindestlänge erfüllt und hier endet",
                        "response": "Eine ausführliche Antwort mit genügend Inhalt, um die Modellvalidierung zu erfüllen. Es muss mindestens 200 Zeichen lang sein, damit die Validierung der Antwort erfolgreich ist. Daher wird hier zusätzlicher Text hinzugefügt, um diese Anforderung zu erfüllen.",
                        "documents": [{"title": "Dokument 1", "url": "https://example.com/doc1"}],
                        "auto_publish": True,
                    }
                },
            }

    client = cast(Any, LangfuseClient.__new__(LangfuseClient))
    setattr(client, "langfuse", SimpleNamespace(api=SimpleNamespace(trace=DummyTraceAPI())))

    input_text, output_text, used_documents, trace_tags = client.get_trace_io(trace_id="answer-trace")

    assert output_text is not None
    assert input_text == "Eine Anfrage"
    assert "Ein sehr langer Antwortbetreff" in output_text
    assert "Eine ausführliche Antwort" in output_text
    assert used_documents == "- [Dokument 1](https://example.com/doc1)\n"
    assert trace_tags == []


def test_resolve_feedback_request_rejects_blank_query_values(german_translations: dict[str, str]) -> None:
    """Reject blank query parameter values before loading trace data."""
    request = _make_request({"trace_id": "   ", "key": "expected-key"})

    authorized, status, query_params = _resolve_feedback_request(
        request=request,
        access_key_configured=True,
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
            return "hello", "world", "!!!", []

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert trace_id == "trace-123"
            assert score_name == "user-thumbs"
            return False

    salt = "secret-salt"
    expected = compute_feedback_token("hello", "world", salt)
    request = _make_request({"trace_id": "trace-123", "key": expected})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert used_documents == "!!!"
    assert status == "Trace geladen"


def test_resolve_score_name_prefers_usecase_tag_match() -> None:
    """The trace's usecase tag selects the configured per-usecase score name."""
    score_names = {"example-usecase": "example-thumbs"}

    assert _resolve_score_name(["example-usecase"], "user-thumbs", score_names) == "example-thumbs"
    assert _resolve_score_name(["unrelated", "example-usecase"], "user-thumbs", score_names) == "example-thumbs"


def test_resolve_score_name_falls_back_to_default_without_match() -> None:
    """Missing or unknown usecase tags fall back to the default score name."""
    score_names = {"example-usecase": "example-thumbs"}

    assert _resolve_score_name([], "user-thumbs", score_names) == "user-thumbs"
    assert _resolve_score_name(["unknown-usecase"], "user-thumbs", score_names) == "user-thumbs"
    assert _resolve_score_name(None, "user-thumbs", None) == "user-thumbs"


def test_resolve_access_key_prefers_usecase_tag_match() -> None:
    """The trace's usecase tag selects the configured per-usecase token salt."""
    access_keys = {"example-usecase": "usecase-salt"}

    assert _resolve_access_key(["example-usecase"], "root-salt", access_keys) == "usecase-salt"
    assert _resolve_access_key(["unrelated", "example-usecase"], "root-salt", access_keys) == "usecase-salt"


def test_resolve_access_key_falls_back_to_default_without_match() -> None:
    """Missing or unknown usecase tags fall back to the default token salt."""
    access_keys = {"example-usecase": "usecase-salt"}

    assert _resolve_access_key([], "root-salt", access_keys) == "root-salt"
    assert _resolve_access_key(["unknown-usecase"], "root-salt", access_keys) == "root-salt"
    assert _resolve_access_key(None, "root-salt", None) == "root-salt"


def test_load_feedback_trace_resolves_score_name_per_usecase(german_translations: dict[str, str]) -> None:
    """Traces tagged with a usecase are checked against that usecase's score name."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "!!!", ["example-usecase"]

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert score_name == "example-thumbs"
            return False

    salt = "secret-salt"
    request = _make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
        score_names={"example-usecase": "example-thumbs"},
        translations=german_translations,
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert used_documents == "!!!"
    assert status == "Trace geladen"


def test_load_feedback_trace_validates_token_with_usecase_salt(german_translations: dict[str, str]) -> None:
    """Traces tagged with a usecase validate their token against that usecase's salt."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "!!!", ["example-usecase"]

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert score_name == "user-thumbs"
            return False

    request = _make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", "usecase-salt")})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf_factory=DummyClient,
        default_access_key="root-salt",
        default_score_name="user-thumbs",
        access_keys={"example-usecase": "usecase-salt"},
        translations=german_translations,
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert used_documents == "!!!"
    assert status == "Trace geladen"


def test_load_feedback_trace_falls_back_to_root_salt_for_unknown_usecase(
    german_translations: dict[str, str],
) -> None:
    """Traces without a matching usecase tag validate their token against the root salt."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "!!!", ["unknown-usecase"]

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

    request = _make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", "root-salt")})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf_factory=DummyClient,
        default_access_key="root-salt",
        default_score_name="user-thumbs",
        access_keys={"example-usecase": "usecase-salt"},
        translations=german_translations,
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert used_documents == "!!!"
    assert status == "Trace geladen"


def test_load_feedback_trace_rejects_root_salt_token_for_usecase_override(
    german_translations: dict[str, str],
) -> None:
    """Tokens signed with the root salt fail validation for usecases with their own salt."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            self.score_checked = False

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "!!!", ["example-usecase"]

        def has_score(self, trace_id: str, score_name: str) -> bool:
            self.score_checked = True
            return False

    client = DummyClient()
    request = _make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", "root-salt")})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf_factory=lambda: client,
        default_access_key="root-salt",
        default_score_name="user-thumbs",
        access_keys={"example-usecase": "usecase-salt"},
        translations=german_translations,
    )

    assert input_text == ""
    assert output_text == ""
    assert used_documents == ""
    assert status == "Ungültiger Zugriffsschlüssel"
    assert client.score_checked is False


def test_submit_feedback_resolves_score_name_per_usecase(german_translations: dict[str, str]) -> None:
    """Feedback is stored under the score name configured for the trace's usecase."""
    attached_score_names: list[str] = []

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "", ["example-usecase"]

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
            attached_score_names.append(score_name)

    salt = "secret-salt"
    result = _submit_feedback(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
        thumbs="up",
        comment="sehr hilfreich",
        user_name=None,
        tags=None,
        allowed_tags=[],
        translations=german_translations,
        score_names={"example-usecase": "example-thumbs"},
    )

    assert result == "Bewertung gespeichert"
    assert attached_score_names == ["example-thumbs"]


def test_submit_feedback_validates_token_with_usecase_salt(german_translations: dict[str, str]) -> None:
    """Feedback submission validates the token against the trace's usecase salt."""
    attached_score_names: list[str] = []

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "", ["example-usecase"]

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
            attached_score_names.append(score_name)

    result = _submit_feedback(
        request=_make_request(
            {"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", "usecase-salt")}
        ),
        lf_factory=DummyClient,
        default_access_key="root-salt",
        default_score_name="user-thumbs",
        thumbs="up",
        comment="sehr hilfreich",
        user_name=None,
        tags=None,
        allowed_tags=[],
        translations=german_translations,
        access_keys={"example-usecase": "usecase-salt"},
    )

    assert result == "Bewertung gespeichert"
    assert attached_score_names == ["user-thumbs"]


def test_load_feedback_trace_hides_io_when_score_exists(german_translations: dict[str, str]) -> None:
    """Do not expose trace content when the requested feedback already exists."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!", []

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
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == ""
    assert output_text == ""
    assert used_documents == ""
    assert status == "Bewertung bereits vorhanden"


def test_load_feedback_trace_supports_empty_output_no_answer_trace(
    german_translations: dict[str, str],
) -> None:
    """No-answer traces may have empty output and still validate their access key."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "", "", []

        def has_score(self, trace_id: str, score_name: str) -> bool:
            assert trace_id == "trace-123"
            assert score_name == "user-thumbs"
            return False

    salt = "secret-salt"
    expected = compute_feedback_token("hello", "trace-123", salt)
    request = _make_request({"trace_id": "trace-123", "key": expected})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == "hello"
    assert output_text == ""
    assert used_documents == ""
    assert status == "Trace geladen"


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
        lf_factory=DummyClient,
        default_access_key="secret-salt",
        default_score_name="user-thumbs",
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
            return "hello", "world", "", []

        def has_score(self, trace_id: str, score_name: str) -> bool:
            raise LangfuseError("lookup failed")

    salt = "secret-salt"
    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == ""
    assert output_text == ""
    assert status == "Fehler beim Laden des Traces"


def test_load_feedback_trace_returns_load_error_when_client_creation_fails(
    german_translations: dict[str, str],
) -> None:
    """Fail closed when the Langfuse client cannot be constructed."""

    def failing_factory() -> LangfuseClient:
        raise RuntimeError("langfuse unreachable")

    request = _make_request({"trace_id": "trace-123", "key": "expected-key"})

    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=request,
        lf_factory=failing_factory,
        default_access_key="secret-salt",
        default_score_name="user-thumbs",
        translations=german_translations,
    )

    assert input_text == ""
    assert output_text == ""
    assert used_documents == ""
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
            self.last_tags: list[str] | None = None
            self.score_name: str | None = None

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!", []

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
            self.last_tags = tags
            self.score_name = score_name

    salt = "secret-salt"
    client = DummyClient()
    result = _submit_feedback(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf_factory=lambda: client,
        default_access_key=salt,
        default_score_name="configured-thumbs",
        thumbs="down",
        comment="Feedback comment",
        user_name=None,
        tags=["outdated information", "unconfigured"],
        allowed_tags=["outdated information"],
        translations=german_translations,
    )

    assert result == "Bewertung gespeichert"
    assert client.last_tags == ["outdated information"]
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
            return "hello", "world", "", []

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
        lf_factory=lambda: client,
        default_access_key=salt,
        default_score_name="user-thumbs",
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
            return "hello", "world", "", []

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
        lf_factory=lambda: client,
        default_access_key=salt,
        default_score_name="user-thumbs",
        thumbs="up",
        comment="valid comment",
        user_name="AB",
        tags=None,
        allowed_tags=[],
        translations=german_translations,
    )

    assert result == "Fehler beim Speichern der Bewertung"
    assert client.evaluation_attached is False


def test_submit_feedback_returns_save_error_when_client_creation_fails(
    german_translations: dict[str, str],
) -> None:
    """Do not attach feedback when the Langfuse client cannot be constructed."""

    def failing_factory() -> LangfuseClient:
        raise RuntimeError("langfuse unreachable")

    salt = "secret-salt"
    result = _submit_feedback(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf_factory=failing_factory,
        default_access_key=salt,
        default_score_name="user-thumbs",
        thumbs="up",
        comment="valid comment",
        user_name="AB",
        tags=None,
        allowed_tags=[],
        translations=german_translations,
    )

    assert result == "Fehler beim Speichern der Bewertung"


def test_submit_feedback_accepts_current_helper_signature(german_translations: dict[str, str]) -> None:
    """Accept valid inputs using the current feedback helper signature."""

    class DummyClient(LangfuseClient):
        def __init__(self) -> None:
            self.evaluation_attached = False

        def get_trace_io(self, trace_id: str):
            assert trace_id == "trace-123"
            return "hello", "world", "!!!", []

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
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
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
            return "hello", "world", "!!!", []

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

    translations = _load_translations("en")
    salt = "secret-salt"
    input_text, output_text, used_documents, status = _load_feedback_trace(
        request=_make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)}),
        lf_factory=DummyClient,
        default_access_key=salt,
        default_score_name="user-thumbs",
        translations=translations,
    )

    assert input_text == "hello"
    assert output_text == "world"
    assert used_documents == "!!!"
    assert status == "Trace loaded"


def test_build_feedback_frontend_load_event_allows_concurrent_page_loads() -> None:
    """Multiple open feedback pages must load in parallel instead of queueing serially."""
    settings = FrontendSettings(feedback=FeedbackSettings(salt="secret-salt"))
    app = build_feedback_frontend(settings)

    load_fns = [fn for fn in app.fns.values() if any(target[1] == "load" for target in fn.targets)]

    assert len(load_fns) == 1
    assert load_fns[0].concurrency_limit is None


def test_build_feedback_frontend_creates_langfuse_client_per_request() -> None:
    """Each feedback request constructs its own Langfuse client via the factory."""
    settings = FrontendSettings(feedback=FeedbackSettings(salt="secret-salt"))
    instances: list[LangfuseClient] = []

    class RecordingClient(LangfuseClient):
        def __init__(self) -> None:
            instances.append(self)

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "", []

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

    app = build_feedback_frontend(settings, langfuse_client_factory=RecordingClient)
    assert instances == []

    load_fns = [fn.fn for fn in app.fns.values() if any(target[1] == "load" for target in fn.targets)]
    load_fn = load_fns[0]
    assert load_fn is not None
    salt = "secret-salt"
    request = _make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)})

    load_fn(request)

    assert len(instances) == 1


def test_build_feedback_frontend_resolves_score_name_per_usecase() -> None:
    """The feedback frontend resolves the score name from the trace's usecase tag."""
    settings = FrontendSettings(feedback=FeedbackSettings(salt="secret-salt"))
    checked_score_names: list[str] = []

    class RecordingClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "", ["example-usecase"]

        def has_score(self, trace_id: str, score_name: str) -> bool:
            checked_score_names.append(score_name)
            return False

    app = build_feedback_frontend(
        settings,
        langfuse_client_factory=RecordingClient,
        feedback_score_names={"example-usecase": "example-thumbs"},
    )

    load_fns = [fn.fn for fn in app.fns.values() if any(target[1] == "load" for target in fn.targets)]
    load_fn = load_fns[0]
    assert load_fn is not None
    salt = "secret-salt"
    request = _make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", salt)})

    load_fn(request)

    assert checked_score_names == ["example-thumbs"]


def test_build_feedback_frontend_resolves_salt_per_usecase() -> None:
    """The feedback frontend validates tokens with the salt of the trace's usecase."""
    settings = FrontendSettings(feedback=FeedbackSettings(salt="root-salt"))
    checked_score_names: list[str] = []

    class RecordingClient(LangfuseClient):
        def __init__(self) -> None:
            pass

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "", ["example-usecase"]

        def has_score(self, trace_id: str, score_name: str) -> bool:
            checked_score_names.append(score_name)
            return False

    app = build_feedback_frontend(
        settings,
        langfuse_client_factory=RecordingClient,
        feedback_salts={"example-usecase": "usecase-salt"},
    )

    load_fns = [fn.fn for fn in app.fns.values() if any(target[1] == "load" for target in fn.targets)]
    load_fn = load_fns[0]
    assert load_fn is not None
    request = _make_request({"trace_id": "trace-123", "key": compute_feedback_token("hello", "world", "usecase-salt")})

    load_fn(request)

    assert checked_score_names == ["user-thumbs"]


def test_build_feedback_frontend_reports_missing_salt_without_langfuse_client() -> None:
    """Requests fail fast when neither the root nor any usecase salt is configured."""
    settings = FrontendSettings()
    instances: list[LangfuseClient] = []

    class RecordingClient(LangfuseClient):
        def __init__(self) -> None:
            instances.append(self)

    app = build_feedback_frontend(settings, langfuse_client_factory=RecordingClient)

    load_fns = [fn.fn for fn in app.fns.values() if any(target[1] == "load" for target in fn.targets)]
    load_fn = load_fns[0]
    assert load_fn is not None
    load_fn(_make_request({"trace_id": "trace-123", "key": "some-key"}))

    assert instances == []


def test_build_feedback_frontend_skips_langfuse_client_for_invalid_requests() -> None:
    """Invalid query parameters must fail before any Langfuse client is created."""
    settings = FrontendSettings(feedback=FeedbackSettings(salt="secret-salt"))
    instances: list[LangfuseClient] = []

    class RecordingClient(LangfuseClient):
        def __init__(self) -> None:
            instances.append(self)

        def get_trace_io(self, trace_id: str):
            return "hello", "world", "", []

        def has_score(self, trace_id: str, score_name: str) -> bool:
            return False

    app = build_feedback_frontend(settings, langfuse_client_factory=RecordingClient)

    load_fns = [fn.fn for fn in app.fns.values() if any(target[1] == "load" for target in fn.targets)]
    load_fn = load_fns[0]
    assert load_fn is not None
    load_fn(_make_request({}))

    assert instances == []
