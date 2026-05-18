"""Settings class for the REST API."""

from pydantic import BaseModel, Field


class APISettings(BaseModel):
    """Settings for the REST API."""

    api_key: str | None = Field(
        description="API key for authenticating REST API requests. If unset, API authentication will be disabled.",
        default=None,
        min_length=32,
    )
