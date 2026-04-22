"""Settings for application logging output."""

from typing import Literal

from pydantic import BaseModel, Field


class LoggingSettings(BaseModel):
    """Settings for logging configuration."""

    format: Literal["json", "plain"] | None = Field(
        description="Logging format to use. Defaults to 'plain' for development mode, 'json' for production mode.",
        default=None,
    )
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = Field(
        description="Logging level for the zammad-ai logger. Defaults to 'DEBUG' for development mode, 'INFO' for production mode.",
        default=None,
    )
