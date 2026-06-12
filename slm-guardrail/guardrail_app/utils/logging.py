"""Minimal logging setup compatible with workflow style."""

import logging
import logging.config
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


def getLogger(name: str = "slm-guardrail") -> logging.Logger:
    """Return a configured logger, applying config once per process."""
    global _configured
    if not _configured:
        logging.config.dictConfig(get_log_config())
        _configured = True
    return logging.getLogger(name)
