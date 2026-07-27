"""Judge generated answers with a structured LLM response and optional Langfuse tracing."""

from logging import Logger
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langfuse import propagate_attributes

from app.errors import TriageJudgeError, classify_provider_error
from app.models.answer import JudgeResult
from app.observe import LangfuseClient
from app.settings.genai import GenAISettings
from app.utils.langchain import extract_structured_response
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.answer.judge")


class JudgeHandler:
    """Judge generated answers with a structured LLM response."""

    def __init__(
        self, genai_settings: GenAISettings, prompt: str, langfuse_client: LangfuseClient | None = None
    ) -> None:
        """Initialize the judge chain for the configured GenAI backend."""
        self.langfuse_client: LangfuseClient | None = langfuse_client

        if not prompt.strip():
            raise ValueError("Judge prompt cannot be empty.")

        match genai_settings.sdk:
            case "openai":
                self.chat_model = ChatOpenAI(
                    model=genai_settings.judge_model or genai_settings.chat_model,
                    temperature=genai_settings.judge_temperature,
                    max_retries=genai_settings.max_retries,
                    reasoning=genai_settings.judge_reasoning_config,
                )
            case _:
                raise ValueError(f"Unsupported GenAI SDK: {genai_settings.sdk}")

        self._judge_agent = create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=(
                f"{prompt}\n\n"
                "When you are ready to produce the final judgment, call exactly one structured response tool "
                "for the JudgeResult schema. Do not return the judgment as free text, markdown, or raw JSON."
            ),
            response_format=ToolStrategy(
                schema=JudgeResult,
                tool_message_content="Answer judgment has been generated.",
            ),
        )

    async def judge_answer(
        self,
        question: str,
        answer: str,
        documents: list[dict[str, Any]],
        session_id: str | None = None,
    ) -> JudgeResult:
        """Judge an answer and return the structured result."""
        session_id, config = self._build_runnable_config(session_id=session_id)

        try:
            with propagate_attributes(session_id=session_id):
                agent_result: dict[str, Any] = await self._judge_agent.ainvoke(
                    input={
                        "messages": [
                            HumanMessage(content=f"Question: {question}\n\nAnswer: {answer}\n\nDocuments: {documents}")
                        ],
                    },
                    config=config,
                )
            return extract_structured_response(agent_result, JudgeResult)
        except Exception as e:
            logger.error("Error during judge invocation", exc_info=True)
            provider_error = classify_provider_error(e)
            raise TriageJudgeError("Judge operation failed", retryable=provider_error.retryable) from e

    def _build_runnable_config(self, session_id: str | None) -> tuple[str, RunnableConfig]:
        """Build a runnable config, creating a session id when needed."""
        resolved_session_id: str | None = session_id.strip() if session_id is not None else None
        if not resolved_session_id:
            resolved_session_id = str(uuid4())

        if self.langfuse_client is None:
            return resolved_session_id, RunnableConfig()

        config: RunnableConfig = self.langfuse_client.build_config(session_id=resolved_session_id)
        return resolved_session_id, config
