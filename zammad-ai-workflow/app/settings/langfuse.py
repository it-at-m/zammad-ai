"""Settings for Langfuse prompt references."""

from pydantic import BaseModel, Field, PositiveInt


class LangfusePrompt(BaseModel):
    """Langfuse prompt identifier, label, and optional version."""

    version: PositiveInt | None = Field(
        description="Explicit version of the prompt in Langfuse",
        default=None,
    )

    label: str = Field(
        description="Label of the prompt in Langfuse",
        default="production",
    )
    name: str = Field(
        description="Name of the prompt in Langfuse",
        examples=["use_case/triage/prompt_name"],
    )
