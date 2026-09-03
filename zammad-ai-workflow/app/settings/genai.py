"""Settings for GenAI integration and model selection."""

from typing import Literal

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt


class BaseGenAISettings(BaseModel):
    """Base settings shared between all GenAI SDK provider configurations.

    Provider-specific settings are modelled in subclasses which include a
    distinguishing `sdk` field so configuration can be discriminated when
    loading from YAML/envs.
    """

    max_retries: NonNegativeInt = Field(
        description="Maximum retry attempts",
        default=3,
    )

    # Chat model configuration with fallbacks
    chat_model: str = Field(
        default="gpt-4.1-mini",
        description="Model to use for completions",
    )
    triage_model: str | None = Field(
        default=None,
        description="Model to use for triage (fallback to chat_model if not set)",
    )
    answer_model: str | None = Field(
        default=None,
        description="Model to use for answer generation (fallback to chat_model if not set)",
    )
    judge_model: str | None = Field(
        default=None,
        description="Model to use for answer evaluation (fallback to chat_model if not set)",
    )

    triage_temperature: NonNegativeFloat = Field(
        description="Temperature for LLM responses (0.0 to 2.0)",
        default=0.0,
        le=2.0,
    )
    answer_temperature: NonNegativeFloat = Field(
        description="Temperature for answer generation model responses (0.0 to 2.0)",
        default=0.0,
        le=2.0,
    )
    judge_temperature: NonNegativeFloat = Field(
        description="Temperature for judge LLM responses (0.0 to 2.0)",
        default=0.0,
        le=2.0,
    )

    # Embedding configuration
    embedding_model: str = Field(
        description="Model to use for embeddings",
        default="text-embedding-3-large",
    )


# OpenAI reasoning effort levels
OpenAiEffortType = Literal["minimal", "low", "medium", "high"]


class GenAIOpenAISettings(BaseGenAISettings):
    """OpenAI-specific GenAI configuration."""

    sdk: Literal["openai"] = Field(description="GenAI SDK to use", default="openai")

    # Optional reasoning configuration for LLM interactions
    triage_reasoning_effort: OpenAiEffortType | None = Field(
        description="Reasoning effort for supporting models",
        default=None,
    )
    answer_reasoning_effort: OpenAiEffortType | None = Field(
        description="Reasoning effort for answer generation model",
        default=None,
    )
    judge_reasoning_effort: OpenAiEffortType | None = Field(
        description="Reasoning effort for judge model",
        default=None,
    )


# Anthropic effort levels
AnthropicEffortType = Literal["max", "xhigh", "high", "medium", "low"]


class ThinkingConfig(BaseModel):
    """Configuration for thinking parameters in GenAI interactions."""

    type: Literal["enabled", "adaptive"] = Field(description="Type of thinking configuration", default="enabled")
    budget_tokens: NonNegativeInt | None = Field(
        description="Budget tokens for thinking configuration", default=None, ge=1024
    )


class GenAIAnthropicSettings(BaseGenAISettings):
    """Anthropic-specific GenAI configuration.

    Allows Anthropic-specific configuration such as default thinking parameters
    and effort mapping. These fields are optional.
    """

    sdk: Literal["anthropic"] = Field(description="GenAI SDK to use", default="anthropic")

    # Default thinking parameters to pass to ChatAnthropic (if supported)
    triage_thinking: ThinkingConfig | None = Field(
        description="Triage thinking configuration",
        default=None,
    )
    answer_thinking: ThinkingConfig | None = Field(
        description="Answer generation thinking configuration",
        default=None,
    )
    judge_thinking: ThinkingConfig | None = Field(
        description="Judge thinking configuration",
        default=None,
    )
    # Convenience shorthand for output effort
    triage_effort: AnthropicEffortType | None = Field(
        description="Default Anthropic effort level for triage operations",
        default=None,
    )
    answer_effort: AnthropicEffortType | None = Field(
        description="Default Anthropic effort level for answer generation",
        default=None,
    )
    judge_effort: AnthropicEffortType | None = Field(
        description="Default Anthropic effort level for judge model",
        default=None,
    )


GenAIProviderSettings = GenAIOpenAISettings | GenAIAnthropicSettings

try:
    from .settings import ZammadAISettings

    ZammadAISettings.model_rebuild()
except Exception:
    pass
