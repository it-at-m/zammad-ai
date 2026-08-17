"""Settings class for the REST API."""

from pydantic import BaseModel, Field, PositiveInt


class APISettings(BaseModel):
    """Settings for the REST API."""

    api_key: str | None = Field(
        description="API key for authenticating REST API requests. If unset, API authentication will be disabled.",
        default=None,
        min_length=32,
    )
    shutdown_timeout_seconds: PositiveInt = Field(
        description="Maximum time Uvicorn waits for open requests during graceful shutdown.",
        default=10,
    )
