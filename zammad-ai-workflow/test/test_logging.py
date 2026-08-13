"""Tests for logging configuration and structlog renderers."""

import json
import logging

import structlog

from app.utils.logging import build_json_formatter, build_plain_formatter, get_log_config, reset_logging_state


def test_build_json_formatter_formats_stdlib_records() -> None:
    """JSON formatter should render stdlib log records with extra fields."""
    formatter = build_json_formatter()
    record = logging.LogRecord(
        name="zammad-ai.tests",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Hello %s",
        args=("World",),
        exc_info=None,
    )
    record.request_id = "req-123"

    rendered = formatter.format(record)
    payload = json.loads(rendered)

    assert payload["event"] == "Hello World"
    assert payload["logger"] == "zammad-ai.tests"
    assert payload["level"] == "info"
    assert payload["request_id"] == "req-123"
    assert "timestamp" in payload


def test_build_plain_formatter_formats_stdlib_records() -> None:
    """Plain formatter should keep messages readable while showing extra fields."""
    formatter = build_plain_formatter()
    record = logging.LogRecord(
        name="zammad-ai.tests",
        level=logging.WARNING,
        pathname=__file__,
        lineno=20,
        msg="Problem detected",
        args=(),
        exc_info=None,
    )
    record.ticket_id = 42

    rendered = formatter.format(record)

    assert "Problem detected" in rendered
    assert "ticket_id=42" in rendered
    assert "warning" in rendered


def test_reset_logging_state_resets_structlog_defaults() -> None:
    """Reset should clear custom structlog configuration between tests."""
    structlog.configure(processors=[])

    reset_logging_state()

    assert structlog.is_configured() is False


def test_get_log_config_prefers_explicit_json_format_in_development(
    monkeypatch,
    settings_factory,
) -> None:
    """Explicit JSON format should win over development mode defaults."""
    settings = settings_factory(mode="development")
    settings.log.format = "json"
    monkeypatch.setattr("app.utils.logging.get_settings", lambda: settings, raising=False)
    monkeypatch.setattr("app.settings.get_settings", lambda: settings)

    log_config = get_log_config()

    assert log_config["handlers"]["console"]["formatter"] == "json"
    assert log_config["handlers"]["httpx"]["formatter"] == "json"
