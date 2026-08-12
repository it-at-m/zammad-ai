"""Separate Gradio frontend for Sachbearbeiter feedback on Langfuse traces."""

from collections.abc import Mapping
from hashlib import sha256
from logging import Logger
from secrets import compare_digest
from typing import Tuple

import gradio as gr

from app.observe.langfuse import LangfuseClient, LangfuseError
from app.settings import FrontendSettings
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.frontend.feedback")


def _request_query_params(request: gr.Request | None) -> Mapping[str, str]:
    if request is None:
        return {}

    underlying_request = getattr(request, "request", None) or request
    query_params = getattr(underlying_request, "query_params", None)
    if query_params is None:
        return {}

    try:
        return {str(key): str(value) for key, value in query_params.items()}
    except Exception:
        return {}


def _resolve_feedback_request(
    request: gr.Request | None,
    expected_access_key: str | None,
    default_score_name: str,
) -> tuple[bool, str, str, str]:
    """Resolve basic request context (trace_id, score_name) and configuration."""
    query_params = _request_query_params(request)
    resolved_trace_id = query_params.get("trace_id", "")
    resolved_score_name = query_params.get("score_name", default_score_name)

    if expected_access_key is None:
        return False, "Zugriffsschlüssel ist nicht konfiguriert", resolved_trace_id, resolved_score_name

    return True, "", resolved_trace_id, resolved_score_name


def _compute_feedback_token(inp: str, out: str, salt: str) -> str:
    """Compute a per-link token from input, output, and a secret salt.

    The token is SHA256 over the UTF-8 bytes of "{inp}|{out}|{salt}".
    """
    base = f"{inp}|{out}|{salt}".encode("utf-8")
    return sha256(base).hexdigest()


def _load_feedback_trace(
    request: gr.Request | None,
    lf: LangfuseClient,
    expected_access_key: str | None,
    default_score_name: str,
) -> Tuple[str, str, str]:
    authorized, status, trace_id, score_name = _resolve_feedback_request(
        request=request,
        expected_access_key=expected_access_key,
        default_score_name=default_score_name,
    )
    if not authorized:
        return "", "", status
    if not trace_id:
        return "", "", "Keine Trace ID in der URL"
    # Load IO first; if the trace is invalid, report that regardless of token
    try:
        inp, out = lf.get_trace_io(trace_id=trace_id)
    except LangfuseError:
        logger.warning("Invalid trace id while loading feedback trace", exc_info=True)
        return "", "", "Ungültige Trace ID oder Trace nicht gefunden"
    except Exception:
        logger.warning("Failed to load trace", exc_info=True)
        return "", "", "Fehler beim Laden des Traces"

    # Verify per-link token from URL query parameter (key/token)
    params = _request_query_params(request)
    provided_key = params.get("key") or params.get("token")
    if not provided_key:
        return "", "", "Kein Zugriffsschlüssel in der URL"

    expected_token = _compute_feedback_token(inp or "", out or "", expected_access_key or "")

    if not compare_digest(provided_key, expected_token):
        return "", "", "Ungültiger Zugriffsschlüssel"

    try:
        if lf.has_score(trace_id=trace_id, score_name=score_name):
            return "", "", "Bewertung bereits vorhanden"
    except Exception:
        logger.warning("Failed to check existing score while loading feedback trace", exc_info=True)

    return inp or "", out or "", "Trace geladen"


def _submit_feedback(
    request: gr.Request | None,
    lf: LangfuseClient,
    expected_access_key: str | None,
    default_score_name: str,
    thumbs: str,
    comment: str,
    user_name: str | None,
) -> str:
    authorized, status, trace_id, score_name = _resolve_feedback_request(
        request=request,
        expected_access_key=expected_access_key,
        default_score_name=default_score_name,
    )
    if not authorized:
        return status
    if not trace_id:
        return "Keine Trace ID in der URL"

    # Load IO to compute expected token
    try:
        inp, out = lf.get_trace_io(trace_id=trace_id)
    except LangfuseError:
        logger.warning("Invalid trace id while storing feedback", exc_info=True)
        return "Ungültige Trace ID oder Trace nicht gefunden"
    except Exception:
        logger.exception("Failed to load trace for feedback submit")
        return "Fehler beim Speichern der Bewertung"

    # Verify per-link token from URL query parameter (key/token)
    params = _request_query_params(request)
    provided_key = params.get("key") or params.get("token")
    if not provided_key:
        return "Kein Zugriffsschlüssel in der URL"
    expected_token = _compute_feedback_token(inp or "", out or "", expected_access_key or "")
    if not compare_digest(provided_key, expected_token):
        return "Ungültiger Zugriffsschlüssel"

    # Enforce single evaluation per trace/score
    try:
        if lf.has_score(trace_id=trace_id, score_name=score_name):
            return "Bewertung bereits vorhanden"
    except Exception:
        logger.warning("Failed to check existing score before storing feedback", exc_info=True)

    thumbs_up: bool = thumbs == "up"
    try:
        # Use provided user name/initials if given, else default label
        user_meta: str = (user_name or "").strip() or "sachbearbeiter"
        lf.attach_evaluation_to_trace(
            trace_id=trace_id,
            thumbs_up=thumbs_up,
            comment=comment,
            user=user_meta,
            score_name=score_name,
        )
        return "Bewertung gespeichert"
    except LangfuseError:
        logger.warning("Invalid trace id while storing feedback", exc_info=True)
        return "Ungültige Trace ID oder Trace nicht gefunden"
    except Exception:
        logger.exception("Failed to attach evaluation to trace")
        return "Fehler beim Speichern der Bewertung"


def build_feedback_frontend(settings: FrontendSettings) -> gr.Blocks:
    """Build a compact Gradio UI mounted separately for feedback collection."""
    lf = LangfuseClient()
    expected_access_key = settings.feedback.salt.get_secret_value() if settings.feedback.salt else None
    default_score_name = settings.feedback.score_name

    def load_feedback(request: gr.Request | None = None):
        input_text, output_text, result = _load_feedback_trace(
            request=request,
            lf=lf,
            expected_access_key=expected_access_key,
            default_score_name=default_score_name,
        )
        if result == "Trace geladen":
            return input_text, output_text, gr.update(visible=True), gr.update(visible=False), ""
        return "", "", gr.update(visible=False), gr.update(visible=True), result

    def submit_feedback(thumbs: str, comment: str, user_name: str | None, request: gr.Request | None = None) -> str:
        return _submit_feedback(
            request=request,
            lf=lf,
            expected_access_key=expected_access_key,
            default_score_name=default_score_name,
            thumbs=thumbs,
            comment=comment,
            user_name=user_name,
        )

    def submit_feedback_up(comment: str, user_name: str | None, request: gr.Request | None = None) -> str:
        return submit_feedback("up", comment, user_name, request)

    def submit_feedback_down(comment: str, user_name: str | None, request: gr.Request | None = None) -> str:
        return submit_feedback("down", comment, user_name, request)

    def display_submission_result(result: str):
        if result == "Bewertung gespeichert":
            return gr.update(visible=False), gr.update(visible=False), "", gr.update(visible=True)
        return gr.update(visible=False), gr.update(visible=True), result, gr.update(visible=False)

    with gr.Blocks(title="Zammad AI Feedback") as feedback_app:
        with gr.Column(visible=False) as error_page:
            gr.Markdown("# Feedback nicht verfügbar")
            error_message = gr.Markdown()

        with gr.Column(visible=False) as success_page:
            gr.Markdown("# Feedback gespeichert")
            gr.Markdown("Feedback wurde erfolgreich gespeichert, Sie können die Seite jetzt schließen.")

        with gr.Column(visible=False) as feedback_page:
            gr.Markdown("# Zammad AI Feedback")

            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("**Original Anfrage**")
                    input_box = gr.Textbox(label="", interactive=False, lines=20, placeholder="Keine Anfrage geladen")
                with gr.Column(scale=1):
                    gr.Markdown("**KI-Antwort**")
                    output_box = gr.Textbox(label="", interactive=False, lines=20, placeholder="Keine Antwort geladen")

            with gr.Row():
                feedback_comment = gr.Textbox(
                    label="Kommentar (optional)",
                    lines=3,
                    placeholder="Kurz begründen, warum die Antwort hilfreich war oder nicht.",
                )
                feedback_user = gr.Textbox(label="Name/Kürzel (optional)", lines=1, placeholder="z. B. AB")

            with gr.Row():
                thumbs_up = gr.Button("👍 Gut", variant="secondary")
                thumbs_down = gr.Button("👎 Schlecht", variant="secondary")

        submission_result = gr.State("")

        feedback_app.load(
            fn=load_feedback,
            outputs=[input_box, output_box, feedback_page, error_page, error_message],
        )
        # Thumbs up submission
        (
            thumbs_up.click(
                fn=submit_feedback_up,
                inputs=[feedback_comment, feedback_user],
                outputs=[submission_result],
            ).then(
                fn=display_submission_result,
                inputs=[submission_result],
                outputs=[feedback_page, error_page, error_message, success_page],
            )
        )
        # Thumbs down submission
        (
            thumbs_down.click(
                fn=submit_feedback_down,
                inputs=[feedback_comment, feedback_user],
                outputs=[submission_result],
            ).then(
                fn=display_submission_result,
                inputs=[submission_result],
                outputs=[feedback_page, error_page, error_message, success_page],
            )
        )

    return feedback_app
