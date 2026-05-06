"""Settings class for the REST API."""

from pydantic import BaseModel, Field


class APISettings(BaseModel):
    """Settings for the REST API."""

    api_key: str | None = Field(
        description="API key for authenticating REST API requests. If unset, API authentication will be disabled.",
        default=None,
        min_length=32,
    )
    api_key_header_name: str = Field(
        description="Name of the HTTP header to be used for API key authentication.",
        default="X-API-Key",
        min_length=1,
    )
