"""Minimal logging setup compatible with workflow style."""

import logging
import logging.config
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer, StackInfoRenderer, TimeStamper, UnicodeDecoder, format_exc_info
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
    """Load logging configuration from the service's logconf.yaml."""
    logconf_path = Path(__file__).resolve().parents[2] / "logconf.yaml"
    with logconf_path.open("r", encoding="utf-8") as file:
        log_config = safe_load(file)

    formatter = "plain" if sys.stdout.isatty() else "json"
    for handler_config in log_config.get("handlers", {}).values():
        if "formatter" in handler_config:
            handler_config["formatter"] = formatter

    return log_config


_configured = False


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
        format_exc_info,
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
    """Build the human-readable formatter used in interactive sessions."""
    return _build_processor_formatter(render_json=False)


def build_json_formatter() -> ProcessorFormatter:
    """Build the JSON formatter used in non-interactive environments."""
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


def reset_logging_state() -> None:
    """Reset cached logging state for tests."""
    global _configured
    get_log_config.cache_clear()
    structlog.reset_defaults()
    _configured = False


def getLogger(name: str = "slm-guardrails") -> logging.Logger:
    """Return a configured logger, applying config once per process."""
    global _configured
    if not _configured:
        _configure_structlog()
        logging.config.dictConfig(get_log_config())
        _configured = True
    return logging.getLogger(name)
