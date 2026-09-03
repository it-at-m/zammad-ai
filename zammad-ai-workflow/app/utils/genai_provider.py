"""Provider factory helpers for creating LangChain chat model instances."""

from __future__ import annotations

from logging import Logger
from typing import Any, Literal

from langchain_core.outputs.chat_result import ChatResult
from langchain_openai import ChatOpenAI

from app.settings.genai import (
    AnthropicEffortType,
    GenAIAnthropicSettings,
    GenAIOpenAISettings,
    GenAIProviderSettings,
    OpenAiEffortType,
    ThinkingConfig,
)
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.genai_provider")

ChatRole = Literal["triage", "answer", "judge"]


class CleanReasoningChatOpenAI(ChatOpenAI):
    """Custom ChatOpenAI subclass to cleanly handle reasoning content in the response."""

    def _create_chat_result(self, response: Any, generation_info: Any = None) -> Any:
        result: ChatResult = super()._create_chat_result(response, generation_info)

        # Pull choices from raw SDK response object
        choices: Any | list[Any] = getattr(response, "choices", [])
        for i, choice in enumerate(choices):
            raw_msg: Any | None = getattr(choice, "message", None)
            if raw_msg and i < len(result.generations):
                # Check for LiteLLM's top-level reasoning_content attribute
                reasoning: Any | None = getattr(raw_msg, "reasoning_content", None)

                # Fallback to provider_specific_fields.reasoning if vLLM put it there
                if not reasoning and hasattr(raw_msg, "provider_specific_fields"):
                    psf = raw_msg.provider_specific_fields or {}
                    reasoning: Any | None = psf.get("reasoning")

                # Safely populate additional_kwargs without modifying msg.content
                if reasoning:
                    result.generations[i].message.additional_kwargs["reasoning_content"] = reasoning

        return result


def _openai_role_config(
    genai_settings: GenAIOpenAISettings, role: ChatRole
) -> tuple[str, float, int, OpenAiEffortType | None]:
    """Return openai model name, temperature and reasoning config for a specific role."""
    match role:
        case "triage":
            model: str = genai_settings.triage_model or genai_settings.chat_model
            temp: float = genai_settings.triage_temperature
            reasoning: OpenAiEffortType | None = genai_settings.triage_reasoning_effort
        case "answer":
            model: str = genai_settings.answer_model or genai_settings.chat_model
            temp: float = genai_settings.answer_temperature
            reasoning: OpenAiEffortType | None = genai_settings.answer_reasoning_effort
        case "judge":
            model: str = genai_settings.judge_model or genai_settings.chat_model
            temp: float = genai_settings.judge_temperature
            reasoning: OpenAiEffortType | None = genai_settings.judge_reasoning_effort
        case _:
            raise ValueError(f"Unsupported GenAI role: {role}")

    return model, temp, genai_settings.max_retries, reasoning


def _anthropic_role_config(
    genai_settings: GenAIAnthropicSettings, role: ChatRole
) -> tuple[str, float, int, ThinkingConfig | None, AnthropicEffortType | None]:
    """Return anthropic model name, temperature and reasoning config for a specific role."""
    match role:
        case "triage":
            model: str = genai_settings.triage_model or genai_settings.chat_model
            temp: float = genai_settings.triage_temperature
            thinking: ThinkingConfig | None = genai_settings.triage_thinking
            effort: AnthropicEffortType | None = genai_settings.triage_effort
        case "answer":
            model: str = genai_settings.answer_model or genai_settings.chat_model
            temp: float = genai_settings.answer_temperature
            thinking: ThinkingConfig | None = genai_settings.answer_thinking
            effort: AnthropicEffortType | None = genai_settings.answer_effort
        case "judge":
            model: str = genai_settings.judge_model or genai_settings.chat_model
            temp: float = genai_settings.judge_temperature
            thinking: ThinkingConfig | None = genai_settings.judge_thinking
            effort: AnthropicEffortType | None = genai_settings.judge_effort
        case _:
            raise ValueError(f"Unsupported GenAI role: {role}")

    return model, temp, genai_settings.max_retries, thinking, effort


def get_chat_model(genai_settings: GenAIProviderSettings, role: ChatRole):
    """Construct a LangChain chat model instance for the configured SDK."""
    match genai_settings.sdk:
        case "openai":
            model_name, temperature, max_retries, reasoning = _openai_role_config(genai_settings, role)
            try:
                chat = CleanReasoningChatOpenAI(
                    model=model_name,
                    temperature=temperature,
                    max_retries=max_retries,
                    reasoning_effort=reasoning,
                    http_socket_options=genai_settings.http_socket_options,
                    use_responses_api=genai_settings.use_responses_api,
                )
                return chat
            except ImportError:
                logger.error("langchain_openai is required for sdk 'openai'", exc_info=True)
                raise
        case "anthropic":
            model_name, temperature, max_retries, thinking, effort = _anthropic_role_config(genai_settings, role)
            try:
                from langchain_anthropic import ChatAnthropic

                chat = ChatAnthropic(
                    model_name=model_name,
                    temperature=temperature,
                    max_retries=max_retries,
                    thinking=thinking.model_dump() if thinking is not None else None,
                    effort=effort,
                )
                return chat
            except ImportError:
                logger.error("langchain_anthropic and anthropic SDK are required for sdk 'anthropic'", exc_info=True)
                raise
        case _:
            raise ValueError(f"Unsupported GenAI SDK: {genai_settings.sdk}")
