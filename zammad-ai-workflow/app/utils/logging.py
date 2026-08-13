"""Logging configuration and formatters for Zammad AI."""

import logging
import logging.config
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer, StackInfoRenderer, TimeStamper, UnicodeDecoder
from structlog.stdlib import (
    BoundLogger,
    ExtraAdder,
    LoggerFactory,
    PositionalArgumentsFormatter,
    ProcessorFormatter,
    add_log_level,
    add_logger_name,
    filter_by_level,
)
from yaml import safe_load


@lru_cache(maxsize=1)
def get_log_config() -> dict[str, Any]:
    """Builds a logging configuration dictionary from the logconf.yaml template and current application settings.

    Selects the formatter to use from `settings.log.format`, applies that formatter to all handlers that declare one, and sets the "zammad-ai" logger level from settings. This function is cached so the configuration is generated once per process.

    Returns:
        dict[str, Any]: A logging configuration dictionary suitable for logging.config.dictConfig.
    """
    from app.settings import get_settings

    settings = get_settings()

    # Read logconf.yaml as template
    logconf_path = Path(__file__).resolve().parents[2] / "logconf.yaml"
    with logconf_path.open("r", encoding="utf-8") as file:
        log_config = safe_load(file)

    # Determine formatter based on settings.
    formatter = "plain" if settings.log.format == "plain" else "json"

    # Update all handlers to use the configured formatter
    for handler_config in log_config.get("handlers", {}).values():
        if "formatter" in handler_config:
            handler_config["formatter"] = formatter

    # Set log level for zammad-ai logger
    if "loggers" in log_config and "zammad-ai" in log_config["loggers"]:
        log_config["loggers"]["zammad-ai"]["level"] = settings.log.level

    return log_config


_logging_configured = False


def reset_logging_state() -> None:
    """Resets the logging state by clearing the cache and resetting the configuration flag."""
    global _logging_configured
    get_log_config.cache_clear()
    structlog.reset_defaults()
    _logging_configured = False


def _shared_processors() -> list[Any]:
    """Return the processors shared by application and stdlib loggers."""
    return [
        structlog.contextvars.merge_contextvars,
        add_logger_name,
        add_log_level,
        ExtraAdder(),
        PositionalArgumentsFormatter(),
        TimeStamper(fmt="iso", utc=True),
        StackInfoRenderer(),
        UnicodeDecoder(),
    ]


def _build_processor_formatter(*, render_json: bool) -> ProcessorFormatter:
    """Build a structlog formatter for stdlib logging handlers."""
    renderer = JSONRenderer() if render_json else ConsoleRenderer(colors=False)
    return ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )


def build_plain_formatter() -> ProcessorFormatter:
    """Build the human-readable formatter used in development."""
    return _build_processor_formatter(render_json=False)


def build_json_formatter() -> ProcessorFormatter:
    """Build the JSON formatter used outside development."""
    return _build_processor_formatter(render_json=True)


def _configure_structlog() -> None:
    """Configure structlog so native structlog loggers integrate with stdlib handlers."""
    structlog.configure(
        processors=[
            filter_by_level,
            *_shared_processors(),
            ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=BoundLogger,
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def getLogger(name: str = "zammad-ai") -> logging.Logger:
    """Configures logging and returns a logger with the specified name.

    Logging configuration is only performed once per process via cached log config.
    Subsequent calls return loggers without reconfiguring.

    Parameters:
        name (str): The name of the logger.

    Returns:
        logging.Logger: The logger with the specified name.
    """
    global _logging_configured
    if not _logging_configured:
        _configure_structlog()
        log_config = get_log_config()
        logging.config.dictConfig(log_config)
        _logging_configured = True
    return logging.getLogger(name)


class MetricsFilter(logging.Filter):
    """Filter out Prometheus metrics endpoint access logs."""

    def filter(self, record):
        """Return True for non-metrics records and False for /metrics requests."""
        return record.getMessage().find("/metrics") == -1


class HealthFilter(logging.Filter):
    """Filter out health check endpoint access logs."""

    def filter(self, record):
        """Return True for non-health check records and False for /api/v1/health requests."""
        return record.getMessage().find("/api/v1/health") == -1


class GradioFilter(logging.Filter):
    """Filter out Gradio endpoint access logs."""

    def filter(self, record):
        """Return True for non-Gradio records and False for /gradio requests."""
        return (
            (record.getMessage().find("/gradio") == -1)
            and (record.getMessage().find("/manifest.json") == -1)
            and (record.getMessage().find("/theme.css") == -1)
            and (record.getMessage().find("/login") == -1)
        )
