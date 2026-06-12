"""Service and factory for preparser instances.

Implements a simple module-level singleton pattern mirroring other services in
the codebase (see guardrails.service). The service will instantiate the
configured preparser type and expose `preparse(message: str) -> str`.
"""

from __future__ import annotations

from typing import Any

from app.preparser.table import TablePreparser
from app.settings.preparser import PreparserSettings, TablePreparserConfig
from app.utils.logging import getLogger

logger = getLogger("zammad-ai.preparser")


class PreparserService:
    """Wrapper around a configured preparser implementation."""

    def __init__(self, settings: PreparserSettings) -> None:
        """Create a PreparserService instance.

        Args:
            settings (PreparserSettings): PreparserSettings object containing relevant settings.

        Raises:
            ValueError: If Preparser is enabled but no config is provided.
            NotImplementedError: If the chosen preparser is not found / implemented.
        """
        self.settings = settings
        self._preparser: Any | None = None

        if not self.settings.enabled:
            logger.debug("Preparser disabled in settings")
            return

        if self.settings.config is None:
            raise ValueError("Preparser enabled but no config provided")

        cfg = self.settings.config
        match getattr(cfg, "type", None):
            case "table":
                assert isinstance(cfg, TablePreparserConfig)
                self._preparser = TablePreparser(
                    keep_rows=cfg.keep_rows,
                    case_sensitive=getattr(cfg, "case_sensitive", False),
                    value_column=getattr(cfg, "value_column", 1),
                )
            case other:
                raise NotImplementedError(f"Unknown preparser config type: {other}")

    def preparse(self, message: str) -> str:
        """Run the configured preparser or return the original message.

        The method is resilient: if parsing fails we return the original message.
        """
        if not self.settings.enabled or self._preparser is None:
            return message

        try:
            return self._preparser.parse(message)
        except Exception:
            logger.error("PreparserService.parse failed; returning original message", exc_info=True)
            return message


_service: PreparserService | None = None


def get_preparser_service(settings: PreparserSettings | None = None) -> PreparserService:
    """Get or create the shared PreparserService instance."""
    global _service
    if _service is None:
        if settings is None:
            settings = PreparserSettings()
        _service = PreparserService(settings=settings)
    return _service
