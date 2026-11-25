"""Shared pytest fixtures for the index job test suite.

This module centralizes deterministic environment defaults, cache cleanup, and
a settings factory for building indexing target configurations in tests.
"""

import os
from collections.abc import Callable, Generator
from typing import Any

import pytest

from job.settings.settings import ZammadAIIndexSettings

_TEST_ENV_DEFAULTS: dict[str, str] = {
    "ZAMMAD_AI_MODE": "unittest",
    "ZAMMAD_AI_DISABLE_YAML": "1",
    "ZAMMAD_AI_ZAMMAD__TYPE": "api",
    "ZAMMAD_AI_ZAMMAD__BASE_URL": "https://zammad.example.com",
    "ZAMMAD_AI_ZAMMAD__AUTH_TOKEN": "test-token",
}


def pytest_configure() -> None:
    """Set deterministic environment defaults before test modules import the job.

    The index job reads its configuration from YAML, dotenv files, and the
    environment; disabling YAML here keeps a local `config.yaml` from leaking
    into tests, and the Zammad defaults allow `get_settings()` to succeed when
    a test imports the application entry point.
    """
    for key, value in _TEST_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


@pytest.fixture(autouse=True)
def cleanup_settings_cache() -> Generator[None, None, None]:
    """Reset cached settings before and after each test."""
    from job.settings.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def cleanup_logging_state() -> Generator[None, None, None]:
    """Reset structlog and logging configuration state before and after each test."""
    from job.utils.logging import reset_logging_state

    reset_logging_state()
    yield
    reset_logging_state()


@pytest.fixture
def settings_factory() -> Callable[..., ZammadAIIndexSettings]:
    """Provide a factory that builds ZammadAIIndexSettings instances for tests.

    The factory pins every field that target resolution depends on (Zammad
    connection, Qdrant overrides, and the target list) via init kwargs so that
    stray environment variables cannot influence test assertions.

    Returns:
        Callable[..., ZammadAIIndexSettings]: A callable accepting `targets`,
        `qdrant`, `zammad`, and arbitrary additional field overrides, returning
        a validated ZammadAIIndexSettings instance.
    """

    def _factory(
        *,
        targets: list[dict[str, Any]] | None = None,
        qdrant: dict[str, Any] | None = None,
        zammad: dict[str, Any] | None = None,
        **overrides: Any,
    ) -> ZammadAIIndexSettings:
        """Create settings from a minimal valid base with optional overrides.

        Parameters:
            targets (list[dict[str, Any]] | None): Target definitions; omit to
                exercise the empty-target error path.
            qdrant (dict[str, Any] | None): Root Qdrant overrides merged into
                the Qdrant defaults.
            zammad (dict[str, Any] | None): Root Zammad overrides merged into
                the base API connection settings.
            **overrides (Any): Additional settings fields applied on top of the
                base payload.

        Returns:
            ZammadAIIndexSettings: A validated settings instance built from
            init kwargs.
        """
        base_zammad: dict[str, Any] = {
            "type": "api",
            "base_url": "https://zammad.example.com",
            "auth_token": "test-token",
        }
        if zammad:
            base_zammad.update(zammad)
        payload: dict[str, Any] = {
            "zammad": base_zammad,
            "qdrant": dict(qdrant) if qdrant is not None else {},
            "mode": "unittest",
        }
        if targets is not None:
            payload["targets"] = targets
        payload.update(overrides)
        return ZammadAIIndexSettings(**payload)

    return _factory
