"""Settings for Langfuse prompt references."""

from pydantic import BaseModel, Field


class LangfusePrompt(BaseModel):
    """Langfuse prompt identifier, label, and optional version."""

    version: int | None = Field(
        description="Explicit version of the prompt in Langfuse",
        default=None,
        ge=1,
    )

    label: str = Field(
        description="Label of the prompt in Langfuse",
        default="production",
    )
    name: str = Field(
        description="Name of the prompt in Langfuse",
        examples=["use_case/triage/prompt_name"],
    )
