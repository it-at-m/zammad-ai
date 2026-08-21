"""Models for guardrail evaluation results (shared shape with workflow)."""

from collections.abc import Sequence
from typing import Any

from guardrail_app.guardrails.labels import JAILBREAK_LABELS, REFUSAL_LABELS, SAFETY_LABELS, TOXICITY_LABELS
from pydantic import BaseModel, Field, field_validator


class _GuardrailLabelListMixin(BaseModel):
    @field_validator(
        "prompt_toxicity",
        "jailbreak_detection",
        "response_toxicity",
        "response_refusal",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def _coerce_label_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, Sequence):
            return [str(item) for item in value]
        return [str(value)]


class GuardrailResult(_GuardrailLabelListMixin):
    """Result of guardrail evaluation for input text."""

    prompt_safety: str = Field(description="Overall safety classification for the input prompt ")
    prompt_toxicity: list[str] = Field(description="Toxicity classification for the input prompt", default_factory=list)
    jailbreak_detection: list[str] = Field(
        description="Jailbreak attempt detection result for the input prompt", default_factory=list
    )
    # optional per-label confidence scores if the model provides them
    label_scores: dict[str, float] = Field(default_factory=dict, description="Per-label confidence scores")
    # raw model output provided for clients who want the full details
    raw_result: dict[str, Any] = Field(default_factory=dict, description="Raw model output")


class GuardrailResponseResult(_GuardrailLabelListMixin):
    """Result of guardrail evaluation for generated response text."""

    response_safety: str = Field(description="Overall safety classification for the generated response")
    response_toxicity: list[str] = Field(
        description="Toxicity classification for the generated response", default_factory=list
    )
    response_refusal: list[str] = Field(
        description="Refusal detection result for the generated response", default_factory=list
    )
    # optional per-label confidence scores if the model provides them
    label_scores: dict[str, float] = Field(default_factory=dict, description="Per-label confidence scores")
    # raw model output provided for clients who want the full details
    raw_result: dict[str, Any] = Field(default_factory=dict, description="Raw model output")


class PromptRequest(BaseModel):
    """Request model for guardrail evaluation of input prompt."""

    text: str
    model: str | None = None
    threshold: float | None = None
    safety_labels: list[str] = Field(default=SAFETY_LABELS, description="List of safety labels to evaluate")
    refusal_labels: list[str] = Field(default=REFUSAL_LABELS, description="List of refusal labels to evaluate")
    toxicity_labels: list[str] = Field(
        default=TOXICITY_LABELS,
        description="List of toxicity labels to evaluate",
    )
    jailbreak_labels: list[str] = Field(
        default=JAILBREAK_LABELS,
        description="List of jailbreak labels to evaluate",
    )

    @field_validator("threshold", mode="before", check_fields=False)
    @classmethod
    def _threshold_must_be_between_0_and_1(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not (0.0 <= value <= 1.0):
            raise ValueError("Threshold must be between 0 and 1")
        return value


class ResponseRequest(BaseModel):
    """Request model for guardrail evaluation of generated response."""

    text: str
    response: str
    model: str | None = None
    threshold: float | None = None
    safety_labels: list[str] = Field(default=SAFETY_LABELS, description="List of safety labels to evaluate")
    refusal_labels: list[str] = Field(default=REFUSAL_LABELS, description="List of refusal labels to evaluate")
    toxicity_labels: list[str] = Field(
        default=TOXICITY_LABELS,
        description="List of toxicity labels to evaluate",
    )
    jailbreak_labels: list[str] = Field(
        default=JAILBREAK_LABELS,
        description="List of jailbreak labels to evaluate",
    )

    @field_validator("threshold", mode="before", check_fields=False)
    @classmethod
    def _threshold_must_be_between_0_and_1(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not (0.0 <= value <= 1.0):
            raise ValueError("Threshold must be between 0 and 1")
        return value
