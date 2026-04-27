"""Mount the optional Gradio frontend into the FastAPI app."""

from logging import Logger

import gradio as gr
from fastapi import FastAPI

from app.settings import FrontendSettings
from app.utils.logging import getLogger

from .ui import build_frontend

logger: Logger = getLogger("zammad-ai.frontend.integration")


def mount_frontend(app: FastAPI, frontend_settings: FrontendSettings) -> FastAPI:
    """Mount a Gradio frontend at the application root when enabled.

    If `frontend_settings.enabled` is False, the original `app` is returned unchanged. When enabled, the frontend is mounted at `/` using credentials from `frontend_settings`.

    Parameters:
        app (FastAPI): The FastAPI application to mount the frontend onto.
        frontend_settings (FrontendSettings): Configuration containing the enable flag and authentication credentials (`auth_username`, `auth_password`).

    Returns:
        FastAPI: The FastAPI application with the Gradio frontend mounted at the root, or the original app if mounting is disabled.
    """
    if not frontend_settings.enabled:
        return app

    auth: tuple[str, str] = (
        frontend_settings.auth_username.get_secret_value(),
        frontend_settings.auth_password.get_secret_value(),
    )

    logger.info("Mounting frontend on root path.")
    frontend = build_frontend(frontend_settings=frontend_settings)

    return gr.mount_gradio_app(
        app=app,
        blocks=frontend,
        path="",
        auth=auth,
    )
