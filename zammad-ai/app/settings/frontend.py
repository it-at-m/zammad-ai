"""Settings for the optional Gradio frontend."""

from pydantic import BaseModel, Field, SecretStr


class FrontendSettings(BaseModel):
    """Settings for the optional frontend."""

    enabled: bool = Field(
        description="Whether to enable the optional frontend for Zammad AI.",
        default=False,
    )
    request_timeout_seconds: float = Field(
        description="HTTP request timeout used by the frontend API calls in seconds.",
        default=30.0,
        gt=0,
    )
    auth_username: SecretStr = Field(
        description="Username for frontend basic auth.",
        default=SecretStr("demo"),
        min_length=4,
    )
    auth_password: SecretStr = Field(
        description="Password for frontend basic auth.",
        default=SecretStr("zammad-ai"),
        min_length=6,
    )
