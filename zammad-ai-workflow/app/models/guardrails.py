"""Models for guardrail evaluation results."""

from pydantic import BaseModel, Field


class GuardrailResult(BaseModel):
    """Result of guardrail evaluation for input text."""

    prompt_safety: str = Field(description="Overall safety classification for the input prompt ")
    prompt_toxicity: list[str] = Field(description="Toxicity classification for the input prompt", default_factory=list)
    jailbreak_detection: list[str] = Field(
        description="Jailbreak attempt detection result for the input prompt", default_factory=list
    )

class GuardrailResponseResult(BaseModel):
    """Result of guardrail evaluation for generated response text."""

    response_safety: str = Field(description="Overall safety classification for the generated response")
    response_toxicity: list[str] = Field(description="Toxicity classification for the generated response", default_factory=list)
    response_refusal: list[str] = Field(
        description="Refusal detection result for the generated response", default_factory=list
    )