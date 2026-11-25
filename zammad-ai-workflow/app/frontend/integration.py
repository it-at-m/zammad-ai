"""Mount the optional Gradio frontend into the FastAPI app."""

from logging import Logger

import gradio as gr
from fastapi import FastAPI

from app.settings import ZammadAISettings
from app.utils.logging import getLogger

from .feedback_ui import build_feedback_frontend
from .ui import build_frontend

logger: Logger = getLogger("zammad-ai.frontend.integration")


def mount_frontend(
    app: FastAPI,
    settings: ZammadAISettings,
    usecase_settings: dict[str, ZammadAISettings] | None = None,
) -> FastAPI:
    """Mount a Gradio frontend at the application root when enabled.

    If `frontend_settings.enabled` is False, the original `app` is returned unchanged. When enabled, the frontend is mounted at `/` using credentials from `frontend_settings`.

    Parameters:
        app (FastAPI): The FastAPI application to mount the frontend onto.
        frontend_settings (FrontendSettings): Configuration containing the enable flag and authentication credentials (`auth_username`, `auth_password`).
        usecase_settings (dict[str, ZammadAISettings] | None): Effective settings per usecase name in multi-usecase mode; lets the frontend render the System Info for the usecase selected in the UI.

    Returns:
        FastAPI: The FastAPI application with the Gradio frontend mounted at the root, or the original app if mounting is disabled.
    """
    if not settings.frontend.enabled:
        return app

    auth: tuple[str, str] = (
        settings.frontend.auth_username.get_secret_value(),
        settings.frontend.auth_password.get_secret_value(),
    )

    logger.info("Mounting frontend at root path.")
    frontend = build_frontend(settings=settings, usecase_settings=usecase_settings)

    return gr.mount_gradio_app(
        app=app,
        blocks=frontend,
        path="/",
        auth=auth,
    )


def mount_feedback_frontend(
    app: FastAPI,
    settings: ZammadAISettings,
    usecase_settings: dict[str, ZammadAISettings] | None = None,
) -> FastAPI:
    """Mount the separate feedback Gradio app at `/feedback` when frontend is enabled.

    This route does not use the main frontend basic auth; access is controlled
    inside the feedback UI through the URL query-string secret key.

    Parameters:
        app (FastAPI): The FastAPI application to mount the feedback frontend onto.
        settings (ZammadAISettings): Root settings providing the default feedback configuration.
        usecase_settings (dict[str, ZammadAISettings] | None): Effective settings per usecase name;
            each usecase's `frontend.feedback.score_name` and `frontend.feedback.salt` are used for
            traces tagged with that usecase, so feedback scores stay separable per usecase in
            Langfuse and feedback links validate against the usecase's salt.
    """
    if not settings.frontend.enabled:
        return app

    logger.info("Mounting feedback frontend at /feedback/")

    usecases = usecase_settings or {}
    feedback_score_names = {name: usecase.frontend.feedback.score_name for name, usecase in usecases.items()}
    feedback_salts = {
        name: salt.get_secret_value()
        for name, usecase in usecases.items()
        if (salt := usecase.frontend.feedback.salt) is not None
    }
    feedback = build_feedback_frontend(
        settings.frontend,
        feedback_score_names=feedback_score_names,
        feedback_salts=feedback_salts,
    )

    return gr.mount_gradio_app(app=app, blocks=feedback, path="/feedback")
