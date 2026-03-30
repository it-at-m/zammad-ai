from typing import Literal

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt


class GenAISettings(BaseModel):
    """
    Settings for GenAI integration, including model selection and configuration.
    API keys and URLs are expected to be provided via environment variables or other secure means.
    """

    # General configuration
    sdk: Literal["openai"] = Field(
        description="GenAI SDK to use",
        default="openai",
    )
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

    # Optional reasoning configuration for LLM interactions
    triage_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = Field(
        description="Reasoning effort for supporting models",
        default=None,
    )
    answer_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = Field(
        description="Reasoning effort for answer generation model",
        default=None,
    )
    judge_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = Field(
        description="Reasoning effort for judge model",
        default=None,
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

    @property
    def triage_store(self) -> bool | None:
        """Determines whether to store interactions based on the configured GenAI SDK."""
        if self.triage_reasoning_effort is not None:
            return False
        return None

    @property
    def triage_reasoning_config(self) -> dict[str, str] | None:
        """Constructs a reasoning configuration dictionary for LLM interactions based on the configured reasoning effort."""
        if self.triage_reasoning_effort is not None:
            return {
                "effort": self.triage_reasoning_effort,
                "summary": "detailed",
            }
        return None

    @property
    def answer_store(self) -> bool | None:
        """Determines whether to store interactions based on the configured GenAI SDK."""
        if self.answer_reasoning_effort is not None:
            return False
        return None

    @property
    def answer_reasoning_config(self) -> dict[str, str] | None:
        """Constructs a reasoning configuration dictionary for LLM interactions based on the configured reasoning effort."""
        if self.answer_reasoning_effort is not None:
            return {
                "effort": self.answer_reasoning_effort,
                "summary": "detailed",
            }
        return None

    @property
    def judge_store(self) -> bool | None:
        """Determines whether to store interactions based on the configured GenAI SDK."""
        if self.judge_reasoning_effort is not None:
            return False
        return None

    @property
    def judge_reasoning_config(self) -> dict[str, str] | None:
        """Constructs a reasoning configuration dictionary for LLM interactions based on the configured reasoning effort."""
        if self.judge_reasoning_effort is not None:
            return {
                "effort": self.judge_reasoning_effort,
                "summary": "detailed",
            }
        return None
