"""Configuration settings for guardrail service."""

from pydantic import BaseModel, Field


class GuardrailSettings(BaseModel):
    """Settings for the guardrail content safety service."""

    enabled: bool = Field(
        default=True,
        description="Enable or disable guardrail checks",
    )
    confidence_threshold: float = Field(
        default=0.7,
        description="Confidence threshold above which harmful content is flagged (0-1)",
        ge=0.0,
        le=1.0,
    )
    block_on_high_risk: bool = Field(
        default=False,
        description="Whether to block processing on high-risk content or just flag it",
    )
