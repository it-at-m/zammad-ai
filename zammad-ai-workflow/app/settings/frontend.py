"""Settings for the optional Gradio frontend."""

from pydantic import BaseModel, Field, SecretStr


class FeedbackSettings(BaseModel):
    """Settings for the optional feedback frontend."""

    post_internal_note: bool = Field(
        description="Whether to post the link to give feedback as an internal note in the ticket.",
        default=False,
    )
    salt: SecretStr | None = Field(
        description="Secret salt used to derive per-link tokens (do not expose).",
        default=None,
    )
    score_name: str = Field(
        description="Name of the Langfuse score written by the feedback frontend.",
        default="user-thumbs",
        min_length=1,
    )


class FrontendSettings(BaseModel):
    """Settings for the optional frontend."""

    enabled: bool = Field(
        description="Whether to enable the optional frontend for Zammad AI.",
        default=False,
    )
    base_url: str = Field(
        description="Base URL for the frontend, used in links and redirects.",
        default="http://localhost:8000",
    )
    request_timeout_seconds: float = Field(
        description="HTTP request timeout used by the frontend API calls in seconds.",
        default=300.0,
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
    feedback: FeedbackSettings = Field(
        description="Settings for the feedback frontend.",
        default=FeedbackSettings(),
    )
