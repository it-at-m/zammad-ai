"""Utility helpers for API request validation."""

from secrets import compare_digest

from fastapi.security import HTTPAuthorizationCredentials

from app.settings.settings import ZammadAISettings, get_settings
from app.utils.logging import getLogger

settings: ZammadAISettings = get_settings()
logger = getLogger("zammad-ai.api.v1.utils")


def check_api_key(provided_key: str | HTTPAuthorizationCredentials | None) -> bool:
    """Check if the provided API key or bearer credentials match the expected API key from settings.

    Args:
        provided_key (str | HTTPAuthorizationCredentials | None): The API key provided in the request header,
            or the HTTPAuthorizationCredentials returned by `HTTPBearer`.

    Returns:
        bool: True if the provided API key is valid, False otherwise.
    """
    expected_key: str | None = settings.api.api_key
    if expected_key is None:
        # If no API key is set in settings, allow all requests
        return True
    if provided_key is None:
        return False

    if isinstance(provided_key, HTTPAuthorizationCredentials):
        provided_value = provided_key.credentials
    else:
        provided_value = provided_key

    return compare_digest(provided_value, expected_key)
