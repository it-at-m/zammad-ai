"""Mount the optional Gradio frontend into the FastAPI app."""

from logging import Logger

import gradio as gr
from fastapi import FastAPI

from app.settings import ZammadAISettings
from app.utils.logging import getLogger

from .feedback_ui import build_feedback_frontend
from .ui import build_frontend

logger: Logger = getLogger("zammad-ai.frontend.integration")


def mount_frontend(app: FastAPI, settings: ZammadAISettings) -> FastAPI:
    """Mount a Gradio frontend at the application root when enabled.

    If `frontend_settings.enabled` is False, the original `app` is returned unchanged. When enabled, the frontend is mounted at `/` using credentials from `frontend_settings`.

    Parameters:
        app (FastAPI): The FastAPI application to mount the frontend onto.
        frontend_settings (FrontendSettings): Configuration containing the enable flag and authentication credentials (`auth_username`, `auth_password`).

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
    frontend = build_frontend(settings=settings)

    return gr.mount_gradio_app(
        app=app,
        blocks=frontend,
        path="/",
        auth=auth,
    )


def mount_feedback_frontend(app: FastAPI, settings: ZammadAISettings) -> FastAPI:
    """Mount the separate feedback Gradio app at `/feedback` when frontend is enabled.

    This route does not use the main frontend basic auth; access is controlled
    inside the feedback UI through the URL query-string secret key.
    """
    if not settings.frontend.enabled:
        return app

    logger.info("Mounting feedback frontend at /feedback/")

    feedback = build_feedback_frontend(settings.frontend)

    return gr.mount_gradio_app(app=app, blocks=feedback, path="/feedback")
