"""Minimal logging setup compatible with workflow style."""

import json
import logging
import logging.config
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from yaml import safe_load


@lru_cache(maxsize=1)
def get_log_config() -> dict[str, Any]:
    """Load logging configuration from the service's logconf.yaml."""
    logconf_path = Path(__file__).resolve().parents[2] / "logconf.yaml"
    with logconf_path.open("r", encoding="utf-8") as file:
        return safe_load(file)


_configured = False


def getLogger(name: str = "slm-guardrails") -> logging.Logger:
    """Return a configured logger, applying config once per process."""
    global _configured
    if not _configured:
        logging.config.dictConfig(get_log_config())
        _configured = True
    return logging.getLogger(name)


class JsonFormatter(logging.Formatter):
    """Format log records as JSON objects."""

    # Standard LogRecord attributes to exclude
    STANDARD_ATTRIBUTES: set[str] = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "getMessage",
        "message",
        "color_message",
    }

    # Precompiled ANSI escape sequence regex (e.g., from colorized loggers like Uvicorn)
    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    _PERCENT_PLACEHOLDER_RE = re.compile(r"%(?:\(|s|d)")

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape sequences from text."""
        return self._ANSI_RE.sub("", text)

    def format(self, record: logging.LogRecord) -> str:
        """Formats the log record as a JSON string.

        Parameters:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: The log record as a JSON string.
        """
        # Compute both standard and colorized messages and choose the one without unresolved
        # %-style placeholders (Uvicorn sometimes stores args only for its own formatter).
        gm = record.getMessage()
        cm = getattr(record, "color_message", None)
        cm_clean = self._strip_ansi(cm) if isinstance(cm, str) and cm else None

        def has_unresolved(msg: str | None) -> bool:
            return bool(msg) and bool(self._PERCENT_PLACEHOLDER_RE.search(msg))

        if cm_clean and not has_unresolved(cm_clean) and has_unresolved(gm):
            message = cm_clean
        else:
            message = gm if gm else (cm_clean or "")

        log_data = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": message,
            "name": record.name,
        }

        # Add exception information if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra fields that were passed via the extra parameter

        # Add any attributes that aren't standard LogRecord attributes
        for key, value in record.__dict__.items():
            if key not in self.STANDARD_ATTRIBUTES and not key.startswith("_"):
                log_data[key] = value

        return json.dumps(log_data, ensure_ascii=False)


class HealthFilter(logging.Filter):
    """Filter out health check endpoint access logs."""

    def filter(self, record):
        """Return True for non-health check records and False for /healthz requests."""
        return record.getMessage().find("/healthz") == -1
