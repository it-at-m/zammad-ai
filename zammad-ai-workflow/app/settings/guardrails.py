"""Configuration settings for remote guardrail HTTP client."""

from pydantic import BaseModel, Field, HttpUrl


class GuardrailSettings(BaseModel):
    """Settings for the remote guardrail content safety service."""

    enabled: bool = Field(
        default=True,
        description="Enable or disable guardrail checks.",
    )
    confidence_threshold: float = Field(
        default=0.7,
        description="Confidence threshold above which harmful content is flagged (0-1).",
        ge=0.0,
        le=1.0,
    )
    block_on_high_risk: bool = Field(
        default=False,
        description="Whether to block processing on high-risk content or just flag it.",
    )
    base_url: HttpUrl = Field(
        default=HttpUrl("http://localhost:8080"),
        description="Base URL of the slm-guardrails FastAPI service (without trailing slash).",
    )
    request_timeout_seconds: float = Field(
        default=3.0,
        description="HTTP request timeout when calling guardrail service.",
        gt=0.0,
    )
    auth_token: str | None = Field(
        default=None,
        description="Optional bearer token for authenticating to the guardrail service.",
    )
    verify_tls: bool = Field(
        default=True,
        description="Verify TLS certificates for HTTPS connections.",
    )
