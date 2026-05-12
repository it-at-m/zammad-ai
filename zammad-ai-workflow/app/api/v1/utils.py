"""Utility helpers for API request validation."""

from secrets import compare_digest

from app.settings.settings import ZammadAISettings, get_settings
from app.utils.logging import getLogger

settings: ZammadAISettings = get_settings()
logger = getLogger("zammad-ai.api.v1.utils")


def check_api_key(provided_key: str | None) -> bool:
    """Check if the provided API key matches the expected API key from settings.

    Args:
        provided_key (str | None): The API key provided in the request header.

    Returns:
        bool: True if the provided API key is valid, False otherwise.
    """
    expected_key = settings.api.api_key
    if expected_key is None:
        # If no API key is set in settings, allow all requests
        return True
    if provided_key is None:
        return False
    return compare_digest(provided_key, expected_key)
