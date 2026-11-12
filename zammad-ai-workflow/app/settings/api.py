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
    max_parse_body_bytes: PositiveInt = Field(
        description=(
            "Maximum request body size in bytes the usecase logging middleware buffers to resolve "
            "the usecase from the JSON body. Larger bodies skip usecase binding but are still "
            "processed in full."
        ),
        default=1024 * 1024,
    )
