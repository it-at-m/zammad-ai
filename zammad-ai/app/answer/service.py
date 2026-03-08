from logging import Logger
from pathlib import Path

from langchain.agents.middleware.types import AgentState, _InputAgentState, _OutputAgentState
from langchain.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.observe import LangfuseClient, LangfuseError
from app.settings import ZammadAISettings
from app.settings.answer import FileAnswerPrompt, LangfuseAnswerPrompt, StringAnswerPrompt
from app.utils.logging import getLogger
from app.utils.prompts import load_prompt

from .agent import AgentContext, StructuredAgentResponse, build_agent
from .dlf import DLFClient
from .knowledgebase import QdrantKBClient

logger: Logger = getLogger("zammad-ai.answer.service")


class AnswerService:
    def __init__(self, settings: ZammadAISettings) -> None:
        # Optionally set up Langfuse client if enabled in settings
        self.langfuse_client: LangfuseClient | None = None
        if settings.langfuse_enabled:
            self.langfuse_client = LangfuseClient()

        # Get the system prompt for the answer agent from settings, supporting multiple sources (Langfuse, file, or string)
        agent_prompt: str
        if isinstance(settings.answer.agent_prompt, LangfuseAnswerPrompt):
            if self.langfuse_client is None:
                raise ValueError("Langfuse must be enabled in settings to use it as a prompt source.")
            try:
                agent_prompt: str = self.langfuse_client.get_prompt(
                    prompt_name=settings.answer.agent_prompt.prompt.name,
                    prompt_label=settings.answer.agent_prompt.prompt.label,
                )
            except LangfuseError:
                logger.error("Failed to fetch agent prompt from Langfuse, exiting.", exc_info=True)
                exit(1)
        elif isinstance(settings.answer.agent_prompt, FileAnswerPrompt):
            agent_prompt = load_prompt(file_path=settings.answer.agent_prompt.prompt)
        elif isinstance(settings.answer.agent_prompt, StringAnswerPrompt):
            agent_prompt = settings.answer.agent_prompt.prompt
        else:
            raise ValueError("Invalid type for answer.agent_prompt in settings.")

        # Setup the user message template as an object variable
        self.user_message_template: PromptTemplate = PromptTemplate.from_template(
            template=load_prompt(file_path=Path("prompts") / "answer" / "user_message_template.prompt.md"),
            template_format="jinja2",
        )

        self.agent: CompiledStateGraph[
            AgentState[StructuredAgentResponse], AgentContext, _InputAgentState, _OutputAgentState[StructuredAgentResponse]  # type: ignore
        ] = build_agent(
            genai_settings=settings.genai,
            system_prompt=agent_prompt,
            dlf_enabled=settings.answer.dlf is not None,
        )

        self.agent_context: AgentContext = AgentContext(
            qdrant_kb_client=QdrantKBClient(
                genai_settings=settings.genai,
                qdrant_settings=settings.answer.qdrant,
            ),
            dlf_client=DLFClient(dlf_settings=settings.answer.dlf) if settings.answer.dlf is not None else None,
        )

    async def generate_answer(
        self,
        user_text: str,
        category: str,
        session_id: str | None = None,
    ) -> StructuredAgentResponse:
        if session_id is None and self.langfuse_client is not None:
            session_id = self.langfuse_client.generate_session_id()
        user_message = HumanMessage(
            content=self.user_message_template.format(
                user_text=user_text,
                category=category,
            )
        )
        config: RunnableConfig = (
            self.langfuse_client.build_config(session_id=session_id) if self.langfuse_client is not None else RunnableConfig()
        )
        agent_result: dict = await self.agent.ainvoke(
            input={"messages": [user_message]},
            config=config,
            context=self.agent_context,
        )
        print("Agent raw result:", agent_result)  # Debug print to inspect the raw output from the agent
        return agent_result["structured_response"]


_service: AnswerService | None = None


def get_answer_service(settings: ZammadAISettings | None = None) -> AnswerService:
    """
    Get or create the shared AnswerService instance.

    Args:
        settings: Optional settings to initialize the AnswerService instance.
                 If not provided, uses get_settings().

    Returns:
        AnswerService: The shared AnswerService instance.
    """
    global _service
    if _service is None:
        if settings is None:
            from app.settings import get_settings

            settings = get_settings()
        _service = AnswerService(settings=settings)
    return _service
