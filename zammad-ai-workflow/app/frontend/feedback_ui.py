"""Separate Gradio frontend for Sachbearbeiter feedback on Langfuse traces."""

from collections.abc import Mapping
from hashlib import sha256
from json import load
from logging import Logger
from pathlib import Path
from secrets import compare_digest
from typing import Literal

import gradio as gr
from pydantic import AliasChoices, BaseModel, Field, ValidationError, field_validator

from app.observe.langfuse import LangfuseClient, LangfuseError
from app.settings import FrontendSettings
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.frontend.feedback")
LOCALE_DIRECTORY = Path(__file__).with_name("locales")


def _load_translations(language: Literal["de", "en"]) -> dict[str, str]:
    """Load the selected feedback frontend translation catalog."""
    with (LOCALE_DIRECTORY / f"{language}.json").open(encoding="utf-8") as locale_file:
        return load(locale_file)


class FeedbackSubmission(BaseModel):
    """Validate feedback values received from the browser."""

    thumbs: Literal["up", "down"]
    comment: str = Field(max_length=2_000)
    user_name: str | None = Field(default=None, max_length=100)


class FeedbackRequestQueryParams(BaseModel):
    """Validate query parameters required for feedback access."""

    trace_id: str | None = Field(default=None, max_length=255)
    access_key: str | None = Field(default=None, validation_alias=AliasChoices("key", "token"), max_length=255)

    @field_validator("trace_id", "access_key")
    @classmethod
    def _validate_non_blank_value(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("query parameter must not be blank")

        return normalized_value


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
    translations: Mapping[str, str],
) -> tuple[bool, str, FeedbackRequestQueryParams | None]:
    """Resolve validated request query parameters and configuration."""
    try:
        query_params = FeedbackRequestQueryParams.model_validate(_request_query_params(request))
    except ValidationError:
        logger.warning("Invalid feedback request query parameters", exc_info=True)
        return False, translations["error.feedback_invalid"], None

    if expected_access_key is None:
        return False, translations["error.access_key_not_configured"], None

    if query_params.trace_id is None:
        return False, translations["error.trace_id_missing"], None

    if query_params.access_key is None:
        return False, translations["error.access_key_missing"], None

    return True, "", query_params


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
    score_name: str,
    translations: Mapping[str, str],
) -> tuple[str, str, str]:
    authorized, status, query_params = _resolve_feedback_request(
        request=request,
        expected_access_key=expected_access_key,
        translations=translations,
    )
    if not authorized or query_params is None:
        return "", "", status

    trace_id = query_params.trace_id
    provided_key = query_params.access_key
    assert trace_id is not None
    assert provided_key is not None

    # Load IO first; if the trace is invalid, report that regardless of token
    try:
        inp, out = lf.get_trace_io(trace_id=trace_id)
    except LangfuseError:
        logger.warning("Invalid trace id while loading feedback trace", exc_info=True)
        return "", "", translations["error.trace_not_found"]
    except Exception:
        logger.warning("Failed to load trace", exc_info=True)
        return "", "", translations["error.trace_load_failed"]

    # Verify per-link token from URL query parameter (key/token)
    expected_token = _compute_feedback_token(inp or "", out or "", expected_access_key or "")

    if not compare_digest(provided_key, expected_token):
        return "", "", translations["error.access_key_invalid"]

    try:
        if lf.has_score(trace_id=trace_id, score_name=score_name):
            return "", "", translations["status.feedback_exists"]
    except Exception:
        logger.warning("Failed to check existing score while loading feedback trace", exc_info=True)
        return "", "", translations["error.trace_load_failed"]

    return inp or "", out or "", translations["status.trace_loaded"]


def _submit_feedback(
    request: gr.Request | None,
    lf: LangfuseClient,
    expected_access_key: str | None,
    score_name: str,
    thumbs: str,
    comment: str,
    user_name: str | None,
    tags: list[str] | None,
    allowed_tags: list[str],
    translations: Mapping[str, str],
) -> str:
    authorized, status, query_params = _resolve_feedback_request(
        request=request,
        expected_access_key=expected_access_key,
        translations=translations,
    )
    if not authorized or query_params is None:
        return status

    trace_id = query_params.trace_id
    provided_key = query_params.access_key
    assert trace_id is not None
    assert provided_key is not None

    try:
        submission: FeedbackSubmission = FeedbackSubmission.model_validate(
            {"thumbs": thumbs, "comment": comment, "user_name": user_name}
        )
    except ValidationError:
        logger.warning("Invalid feedback submission", exc_info=True)
        return translations["error.feedback_invalid"]

    # Load IO to compute expected token
    try:
        inp, out = lf.get_trace_io(trace_id=trace_id)
    except LangfuseError:
        logger.warning("Invalid trace id while storing feedback", exc_info=True)
        return translations["error.trace_not_found"]
    except Exception:
        logger.exception("Failed to load trace for feedback submit")
        return translations["error.feedback_save_failed"]

    # Verify per-link token from URL query parameter (key/token)
    expected_token = _compute_feedback_token(inp or "", out or "", expected_access_key or "")
    if not compare_digest(provided_key, expected_token):
        return translations["error.access_key_invalid"]

    # Enforce single evaluation per trace/score
    try:
        if lf.has_score(trace_id=trace_id, score_name=score_name):
            return translations["status.feedback_exists"]
    except Exception:
        logger.warning("Failed to check existing score before storing feedback", exc_info=True)
        return translations["error.feedback_save_failed"]

    try:
        # Use provided user name/initials if given, else default label
        user_meta: str = (submission.user_name or "").strip() or "sachbearbeiter"
        selected_tags = [tag for tag in tags or [] if tag in allowed_tags]
        lf.attach_evaluation_to_trace(
            trace_id=trace_id,
            thumbs_up=submission.thumbs == "up",
            comment=submission.comment,
            user=user_meta,
            tags=selected_tags,
            score_name=score_name,
        )
        return translations["status.feedback_saved"]
    except LangfuseError:
        logger.warning("Invalid trace id while storing feedback", exc_info=True)
        return translations["error.trace_not_found"]
    except Exception:
        logger.exception("Failed to attach evaluation to trace")
        return translations["error.feedback_save_failed"]


def build_feedback_frontend(settings: FrontendSettings) -> gr.Blocks:
    """Build a compact Gradio UI mounted separately for feedback collection."""
    lf = LangfuseClient()
    expected_access_key = settings.feedback.salt.get_secret_value() if settings.feedback.salt else None
    score_name = settings.feedback.score_name
    allowed_tags = settings.feedback.tags
    translations = _load_translations(settings.feedback.language)

    def load_feedback(request: gr.Request | None = None):
        input_text, output_text, result = _load_feedback_trace(
            request=request,
            lf=lf,
            expected_access_key=expected_access_key,
            score_name=score_name,
            translations=translations,
        )
        if result == translations["status.trace_loaded"]:
            return input_text, output_text, gr.update(visible=True), gr.update(visible=False), ""
        return "", "", gr.update(visible=False), gr.update(visible=True), result

    def submit_feedback(
        thumbs: str,
        comment: str,
        user_name: str | None,
        tags: list[str] | None,
        request: gr.Request | None = None,
    ) -> str:
        return _submit_feedback(
            request=request,
            lf=lf,
            expected_access_key=expected_access_key,
            score_name=score_name,
            thumbs=thumbs,
            comment=comment,
            user_name=user_name,
            tags=tags,
            allowed_tags=allowed_tags,
            translations=translations,
        )

    def submit_feedback_up(
        comment: str,
        user_name: str | None,
        tags: list[str] | None,
        request: gr.Request | None = None,
    ) -> str:
        return submit_feedback("up", comment, user_name, tags, request)

    def submit_feedback_down(
        comment: str,
        user_name: str | None,
        tags: list[str] | None,
        request: gr.Request | None = None,
    ) -> str:
        return submit_feedback("down", comment, user_name, tags, request)

    def display_submission_result(result: str):
        if result == translations["status.feedback_saved"]:
            return gr.update(visible=False), gr.update(visible=False), "", gr.update(visible=True)
        return gr.update(visible=False), gr.update(visible=True), result, gr.update(visible=False)

    with gr.Blocks(title=translations["ui.page_title"]) as feedback_app:
        with gr.Column(visible=False) as error_page:
            gr.Markdown(translations["ui.error_title"])
            error_message = gr.Markdown()

        with gr.Column(visible=False) as success_page:
            gr.Markdown(translations["ui.success_title"])
            gr.Markdown(translations["ui.success_message"])

        with gr.Column(visible=False) as feedback_page:
            gr.Markdown(f"# {translations['ui.page_title']}")

            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown(translations["ui.input_label"])
                    input_box = gr.Textbox(
                        label="", interactive=False, lines=20, placeholder=translations["ui.input_placeholder"]
                    )
                with gr.Column(scale=1):
                    gr.Markdown(translations["ui.output_label"])
                    output_box = gr.Textbox(
                        label="", interactive=False, lines=20, placeholder=translations["ui.output_placeholder"]
                    )

            with gr.Row():
                feedback_comment = gr.Textbox(
                    label=translations["ui.comment_label"],
                    lines=3,
                    placeholder=translations["ui.comment_placeholder"],
                )
                feedback_user = gr.Textbox(
                    label=translations["ui.user_label"],
                    lines=1,
                    placeholder=translations["ui.user_placeholder"],
                    visible=False,
                )  # hidden for now, can be enabled if needed

            feedback_tags = gr.CheckboxGroup(
                choices=allowed_tags,
                label=translations["ui.tags_label"],
                visible=bool(allowed_tags),
            )

            with gr.Row():
                thumbs_up = gr.Button("👍 " + translations["ui.thumbs_up"], variant="secondary")
                thumbs_down = gr.Button("👎 " + translations["ui.thumbs_down"], variant="secondary")

        submission_result = gr.State("")

        feedback_app.load(
            fn=load_feedback,
            outputs=[input_box, output_box, feedback_page, error_page, error_message],
        )
        # Thumbs up submission
        (
            thumbs_up.click(  # ty: ignore[unresolved-attribute]
                fn=submit_feedback_up,
                inputs=[feedback_comment, feedback_user, feedback_tags],
                outputs=[submission_result],
            ).then(
                fn=display_submission_result,
                inputs=[submission_result],
                outputs=[feedback_page, error_page, error_message, success_page],
            )
        )
        # Thumbs down submission
        (
            thumbs_down.click(  # ty: ignore[unresolved-attribute]
                fn=submit_feedback_down,
                inputs=[feedback_comment, feedback_user, feedback_tags],
                outputs=[submission_result],
            ).then(
                fn=display_submission_result,
                inputs=[submission_result],
                outputs=[feedback_page, error_page, error_message, success_page],
            )
        )

    return feedback_app
