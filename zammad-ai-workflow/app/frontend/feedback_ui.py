"""Separate Gradio frontend for Sachbearbeiter feedback on Langfuse traces."""
from collections.abc import Mapping
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
    query_params = _request_query_params(request)
    resolved_trace_id = query_params.get("trace_id", "")
    resolved_score_name = query_params.get("score_name", default_score_name)

    if expected_access_key is None:
        return False, "Zugriffsschlüssel ist nicht konfiguriert", resolved_trace_id, resolved_score_name

    provided_key = query_params.get("key") or query_params.get("secret_key") or query_params.get("access_key")
    if not provided_key:
        return False, "Kein Zugriffsschlüssel in der URL", resolved_trace_id, resolved_score_name

    if not compare_digest(provided_key, expected_access_key):
        return False, "Ungültiger Zugriffsschlüssel", resolved_trace_id, resolved_score_name

    return True, "", resolved_trace_id, resolved_score_name


def _load_feedback_trace(
    request: gr.Request | None,
    lf: LangfuseClient,
    expected_access_key: str | None,
    default_score_name: str,
) -> Tuple[str, str, str]:
    authorized, status, trace_id, _score_name = _resolve_feedback_request(
        request=request,
        expected_access_key=expected_access_key,
        default_score_name=default_score_name,
    )
    if not authorized:
        return "", "", status
    if not trace_id:
        return "", "", "Keine Trace ID in der URL"
    try:
        inp, out = lf.get_trace_io(trace_id=trace_id)
        return inp or "", out or "", "Trace geladen"
    except LangfuseError:
        logger.warning("Invalid trace id while loading feedback trace", exc_info=True)
        return "", "", "Ungültige Trace ID oder Trace nicht gefunden"
    except Exception:
        logger.warning("Failed to load trace", exc_info=True)
        return "", "", "Fehler beim Laden des Traces"


def _submit_feedback(
    request: gr.Request | None,
    lf: LangfuseClient,
    expected_access_key: str | None,
    default_score_name: str,
    thumbs: str,
    comment: str,
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
    thumbs_up = thumbs == "up"
    try:
        lf.attach_evaluation_to_trace(
            trace_id=trace_id,
            thumbs_up=thumbs_up,
            comment=comment,
            user="sachbearbeiter",
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
    """Build a compact Gradio UI mounted separately for feedback collection.

    The UI accepts a Langfuse `trace_id`, loads a representative input and
    output from the trace, and lets the Sachbearbeiter submit a thumbs up/down
    plus an optional comment. All writes use the server-side Langfuse secret.
    """
    lf = LangfuseClient()
    expected_access_key = settings.feedback_access_key.get_secret_value() if settings.feedback_access_key else None
    default_score_name = settings.feedback_score_name

    def load_feedback(request: gr.Request | None = None) -> Tuple[str, str, str]:
        return _load_feedback_trace(
            request=request,
            lf=lf,
            expected_access_key=expected_access_key,
            default_score_name=default_score_name,
        )

    def submit_feedback(thumbs: str, comment: str, request: gr.Request | None = None) -> str:
        return _submit_feedback(
            request=request,
            lf=lf,
            expected_access_key=expected_access_key,
            default_score_name=default_score_name,
            thumbs=thumbs,
            comment=comment,
        )

    with gr.Blocks(title="Zammad AI Feedback") as feedback_app:
        gr.Markdown("# Zammad AI Feedback")

        with gr.Row():
            status = gr.Textbox(label="Status", interactive=False)

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("**Original Anfrage**")
                input_box = gr.Textbox(label="", interactive=False, lines=20, placeholder="Keine Anfrage geladen")
            with gr.Column(scale=1):
                gr.Markdown("**KI-Antwort**")
                output_box = gr.Textbox(label="", interactive=False, lines=20, placeholder="Keine Antwort geladen")

        with gr.Row():
            feedback_choice = gr.Radio(choices=["up", "down"], value="up", label="Bewertung (Daumen)")
            feedback_comment = gr.Textbox(
                label="Kommentar (optional)",
                lines=3,
                placeholder="Kurz begründen, warum die Antwort hilfreich war oder nicht.",
            )
            feedback_submit = gr.Button("Absenden", variant="primary")

        # initial load and explicit refresh
        feedback_app.load(fn=load_feedback, outputs=[input_box, output_box, status])
        feedback_submit.click(fn=submit_feedback, inputs=[feedback_choice, feedback_comment], outputs=[status])

    return feedback_app
