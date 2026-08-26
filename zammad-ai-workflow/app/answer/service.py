"""Answer service orchestration for triaged ticket responses."""

import re
from logging import Logger
from time import perf_counter

from langchain.agents.middleware.types import AgentState
from langchain.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables.config import RunnableConfig
from langfuse import observe, propagate_attributes
from langfuse.model import PromptClient
from langgraph.graph.state import CompiledStateGraph
from prometheus_client import Gauge, Histogram

from app.errors import AnswerServiceError, AppError
from app.models.answer import AnswerCandidate, NoAnswerPossible
from app.observe import LangfuseClient, LangfuseError
from app.settings import ZammadAISettings
from app.settings.answer import (
    FilePromptConfig,
    JudgeSettings,
    LangfusePromptConfig,
    StringPromptConfig,
)
from app.utils.context_builders import build_answer_context, build_judge_context, merge_contexts
from app.utils.genai_provider import get_chat_model
from app.utils.jinja2 import PromptTemplateRenderer, get_template_renderer
from app.utils.langchain import extract_structured_response, with_recursion_limit
from app.utils.logging import getLogger
from app.utils.paths import get_prompts_dir
from app.utils.prompts import load_prompt

from .agent import AgentContext, build_agent
from .dlf import DLFClient
from .judge import JudgeHandler, JudgeResult
from .knowledgebase import QdrantKBClient
from .middleware import _format_answer

logger: Logger = getLogger("zammad-ai.answer.service")

ANSWER_RUN_DURATION_SECONDS = Histogram(
    name="zammad_ai_answer_run_duration_seconds",
    documentation="Duration of answer service runs in seconds.",
    labelnames=("outcome",),
)

ANSWER_RUNS_IN_PROGRESS = Gauge(
    name="zammad_ai_answer_runs_in_progress",
    documentation="Number of answer runs currently in progress.",
)


class AnswerService:
    """Service that coordinates prompt loading, agent execution, and cleanup."""

    def __init__(self, settings: ZammadAISettings) -> None:
        # Optionally set up Langfuse client if enabled in settings
        """Initialize the AnswerService, configuring prompt sources, the agent, and supporting clients from the provided settings.

        The initializer:
        - Optionally creates a Langfuse client when langfuse is enabled.
        - Resolves the agent system prompt from one of: Langfuse, a file, or a string in settings.
        - Loads the user message template from the prompts directory.
        - Builds the compiled agent graph using genai settings and the resolved system prompt.
        - Creates a Qdrant knowledge-base client and an optional DLF client.
        - Assembles the AgentContext with the KB and DLF clients.

        Parameters:
            settings (ZammadAISettings): Configuration used to enable integrations and supply prompts, GenAI, Qdrant, and DLf settings.

        Raises:
            ValueError: If Langfuse is referenced as the prompt source but Langfuse is not enabled in settings.
            ValueError: If `settings.answer.agent_prompt` is not a supported prompt source type.

        Notes:
            If fetching the prompt from Langfuse fails, the process exits with status code 1.
        """
        self.settings: ZammadAISettings = settings

        self.langfuse_client: LangfuseClient | None = None
        if settings.langfuse_enabled:
            self.langfuse_client = LangfuseClient()

        self.agent_prompt, self.agent_prompt_version, self.agent_langfuse_prompt = self._resolve_prompt(
            prompt_config=settings.answer.agent_prompt,
            prompt_source_name="agent system prompt",
        )

        self.answer_chat_model = get_chat_model(settings.genai, "answer")

        self.format_prompt, self.format_prompt_version, self.format_langfuse_prompt = self._resolve_prompt(
            prompt_config=settings.answer.format_prompt,
            prompt_source_name="format prompt",
        )

        self.judge_settings: JudgeSettings = settings.answer.judge
        self.judge_handler: JudgeHandler | None = None
        if self.judge_settings.enabled:
            self.judge_prompt, self.judge_prompt_version, self.judge_langfuse_prompt = self._resolve_prompt(
                prompt_config=self.judge_settings.prompt,
                prompt_source_name="judge prompt",
            )
            self.judge_handler = JudgeHandler(
                genai_settings=settings.genai,
                prompt=self.judge_prompt,
                langfuse_client=self.langfuse_client,
                langfuse_prompt=self.judge_langfuse_prompt,
            )
            logger.info("Judge handler initialized and enabled for answer evaluation and repair.")

        # Setup the user message template as an object variable
        # Render with Jinja2 if the template contains Jinja2 syntax
        renderer: PromptTemplateRenderer = get_template_renderer()
        user_msg_template_str = load_prompt(file_path=get_prompts_dir() / "answer" / "user_message_template.prompt.md")
        if renderer._has_jinja2_syntax(user_msg_template_str):
            context = build_answer_context(settings.answer)
            user_msg_template_str = renderer.render_template(user_msg_template_str, context)

        self.user_message_template: PromptTemplate = PromptTemplate.from_template(
            template=user_msg_template_str,
        )

        self.agent: CompiledStateGraph[
            AgentState[AnswerCandidate], AgentContext, AgentState, AgentState[AnswerCandidate]  # type: ignore
        ] = build_agent(
            genai_settings=settings.genai,
            agent_prompt=self.agent_prompt,
            dlf_enabled=settings.answer.dlf is not None,
            laws=settings.answer.laws,
        )
        self.qdrant_kb_client = QdrantKBClient(
            genai_settings=settings.genai,
            qdrant_settings=settings.answer.qdrant,
        )
        self.dlf_client: DLFClient | None = (
            DLFClient(dlf_settings=settings.answer.dlf) if settings.answer.dlf is not None else None
        )
        self.agent_context: AgentContext = AgentContext(
            qdrant_kb_client=self.qdrant_kb_client,
            dlf_client=self.dlf_client,
        )

    @observe(as_type="span")
    async def generate_answer(
        self,
        user_text: str,
        category: str,
        session_id: str | None = None,
    ) -> AnswerCandidate | NoAnswerPossible:
        """Generate a structured answer for the given user text and category, optionally associating the request with a provided Langfuse session.

        Parameters:
            user_text (str): The user's input text to be answered.
            category (str): The category or topic context to include in the user message.
            session_id (str | None): Optional session identifier used for Langfuse tracing; if omitted and Langfuse is enabled, a session id will be generated.

        Returns:
            StructuredAgentResponse: The agent's structured response containing the answer and associated metadata (for example retrieval context and tracing information).
        """
        start_time: float = perf_counter()
        outcome: str = "error"
        ANSWER_RUNS_IN_PROGRESS.inc()
        logger.debug(f"Answer generation with payload:\nuser_text: {user_text}\ncategory: {category}")
        try:
            if session_id is None and self.langfuse_client is not None:
                session_id = self.langfuse_client.generate_session_id()
            agent_langfuse_prompt = getattr(self, "agent_langfuse_prompt", None)
            user_message = HumanMessage(
                content=self.user_message_template.format(
                    user_text=user_text,
                    category=category,
                )
            )
            config: RunnableConfig = (
                self.langfuse_client.build_config(
                    session_id=session_id,
                    langfuse_prompt=agent_langfuse_prompt,
                )
                if self.langfuse_client is not None
                else RunnableConfig()
            )
            # Create a fresh AgentContext per request to avoid leaking runtime state
            # (such as `searched_laws`) between different answer generations. The
            # service previously reused a single AgentContext instance which could
            # cause a law to appear already-searched if a prior request added it.
            #
            # In unit tests the AnswerService is often constructed partially
            # (via __new__) and test helpers inject an `agent_context` stub but do
            # not provide a qdrant_kb_client. In that case prefer the existing
            # `agent_context` to remain compatible with tests. In production the
            # real qdrant_kb_client will be present and a fresh per-request
            # AgentContext is created.
            if hasattr(self, "qdrant_kb_client"):
                per_request_context = AgentContext(
                    qdrant_kb_client=self.qdrant_kb_client,
                    dlf_client=self.dlf_client,
                )
            else:
                per_request_context = getattr(self, "agent_context")

            with propagate_attributes(session_id=session_id):
                agent_result = await self.agent.ainvoke(
                    input={"messages": [user_message]},
                    config=with_recursion_limit(config),
                    context=per_request_context,
                )

            agent_structured_response: AnswerCandidate | NoAnswerPossible = extract_structured_response(
                agent_result,
                (AnswerCandidate, NoAnswerPossible),
            )
            # Pass the per-request AgentContext into the judge/repair flow so
            # repairs use the same request-scoped context (including
            # `searched_laws`) and do not leak state between requests.
            structured_response: AnswerCandidate | NoAnswerPossible = await self._judge_and_repair(
                user_text=user_text,
                category=category,
                user_message=user_message,
                structured_response=agent_structured_response,
                session_id=session_id,
                config=config,
                context=per_request_context,
            )

            if isinstance(structured_response, AnswerCandidate):
                try:
                    formatted_response = await _format_answer(
                        self.answer_chat_model,
                        structured_response,
                        self.langfuse_client,
                        self.format_prompt,
                        self.format_langfuse_prompt,
                        session_id=session_id,
                    )
                    structured_response.response = formatted_response.response
                    structured_response.subject = formatted_response.subject
                except Exception:
                    logger.error("Failed to format final answer.", exc_info=True)

            # Sanitize Markdown asterisks used for emphasis (e.g. **bold**, *italic*)
            # to avoid the frontend/model re-rendering them and consuming context.
            def _sanitize_asterisks(s: str) -> str:
                if not s:
                    return s
                # Remove triple asterisks first, then double, then single.
                s = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", s, flags=re.DOTALL)
                s = re.sub(r"\*\*(.+?)\*\*", r"\1", s, flags=re.DOTALL)
                # Match single-star emphasis like *word* but avoid list markers '* item'.
                s = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", s, flags=re.DOTALL)
                return s

            if isinstance(structured_response, AnswerCandidate):
                structured_response.response = _sanitize_asterisks(structured_response.response)
                if structured_response.subject:
                    structured_response.subject = _sanitize_asterisks(structured_response.subject)
            if isinstance(structured_response, NoAnswerPossible):
                outcome = "no_answer"
            else:
                if self.settings.answer.ai_answer_disclaimer:
                    structured_response.response += f"\n\n{self.settings.answer.ai_answer_disclaimer}"
                outcome = "success"
            return structured_response
        except AppError:
            raise
        except Exception as e:
            logger.error("Answer generation failed.", exc_info=True)
            raise AnswerServiceError("Answer generation failed", retryable=True) from e
        finally:
            ANSWER_RUN_DURATION_SECONDS.labels(outcome=outcome).observe(perf_counter() - start_time)
            ANSWER_RUNS_IN_PROGRESS.dec()

    @observe(as_type="span")
    async def _judge_and_repair(
        self,
        user_text: str,
        category: str,
        user_message: HumanMessage,
        structured_response: AnswerCandidate | NoAnswerPossible,
        session_id: str | None,
        config: RunnableConfig,
        context: AgentContext,
    ) -> AnswerCandidate | NoAnswerPossible:
        """Run judgment and optionally repair a response that failed checks."""
        if isinstance(structured_response, NoAnswerPossible):
            return structured_response

        structured_response.auto_publish = True
        if self.judge_handler is None:
            return structured_response
        repair_prompt, _, repair_langfuse_prompt = self._resolve_prompt(
            prompt_config=self.judge_settings.repair_prompt,
            prompt_source_name="judge repair prompt",
        )
        messages = [user_message]
        for x in range(self.judge_settings.max_repairs + 1):
            judgment: JudgeResult = await self.judge_handler.judge_answer(
                question=user_text,
                answer=structured_response.response,
                documents=[document.model_dump() for document in structured_response.documents],
                session_id=session_id,
            )

            if self._is_judged_ok(judgment):
                logger.debug("Answer passed judgment without need for repair.")
                return structured_response

            if x == self.judge_settings.max_repairs:
                break

            repair_message = HumanMessage(
                content=repair_prompt.format(
                    question=user_text,
                    category=category,
                    answer=structured_response.response,
                    judgment_reasoning=judgment.reasoning,
                    repair_instructions=judgment.repair_instructions or "Please improve the answer.",
                )
            )
            # Use the provided per-request context for repair invocations so
            # runtime state (e.g. which laws were searched) remains request
            # scoped.
            with propagate_attributes(session_id=session_id):
                agent_result: dict = await self.agent.ainvoke(
                    input={"messages": messages + [repair_message]},
                    config=(
                        self.langfuse_client.build_config(
                            session_id=session_id,
                            langfuse_prompt=repair_langfuse_prompt,
                        )
                        if self.langfuse_client is not None
                        else config
                    ),
                    context=context,
                )

            structured_response = extract_structured_response(
                agent_result,
                (AnswerCandidate, NoAnswerPossible),
            )
            if isinstance(structured_response, NoAnswerPossible):
                return structured_response
        logger.debug(
            f"Answer failed judgment after {self.judge_settings.max_repairs} repairs, returning final response."
        )
        structured_response.auto_publish = False
        return structured_response

    def _is_judged_ok(self, judgment: JudgeResult) -> bool:
        """Return whether a judgment meets the configured quality thresholds."""
        return (
            judgment.passed
            and judgment.context_relevance >= self.judge_settings.thresholds.context_relevance
            and judgment.groundedness >= self.judge_settings.thresholds.groundedness
            and judgment.answer_relevance >= self.judge_settings.thresholds.answer_relevance
        )

    def _resolve_prompt(
        self,
        prompt_config: StringPromptConfig | FilePromptConfig | LangfusePromptConfig,
        prompt_source_name: str,
    ) -> tuple[str, int | None, PromptClient | None]:
        """Resolve a prompt from settings, a file, or Langfuse."""
        version: int | None = None
        langfuse_prompt: PromptClient | None = None
        match prompt_config:
            case LangfusePromptConfig():
                if self.langfuse_client is None:
                    raise ValueError(
                        f"Langfuse must be enabled in settings to use it as a {prompt_source_name} source."
                    )
                try:
                    langfuse_prompt_info = prompt_config.prompt
                    template_content, version, langfuse_prompt_ref = self.langfuse_client.get_prompt_with_reference(
                        prompt_name=langfuse_prompt_info.name,
                        prompt_label=langfuse_prompt_info.label,
                    )
                    return template_content, version, langfuse_prompt_ref
                except LangfuseError as e:
                    logger.error(f"Failed to fetch {prompt_source_name} from Langfuse.", exc_info=True)
                    raise AnswerServiceError(
                        f"Failed to fetch {prompt_source_name} from Langfuse",
                        retryable=True,
                    ) from e
            case FilePromptConfig():
                template_content: str = load_prompt(file_path=prompt_config.prompt)
            case StringPromptConfig():
                template_content: str = prompt_config.prompt
            case _:
                raise ValueError(f"Invalid type for {prompt_source_name} in settings.")

        renderer: PromptTemplateRenderer = get_template_renderer()
        if renderer._has_jinja2_syntax(template_content):
            # Provide both answer and judge contexts so templates like the
            # judge prompt can access 'thresholds', 'repair_enabled', etc.
            answer_ctx = build_answer_context(self.settings.answer)
            judge_ctx = build_judge_context(self.settings)
            context = merge_contexts(answer_ctx, judge_ctx)
            return renderer.render_template(template_content, context), version, langfuse_prompt
        else:
            return template_content, version, langfuse_prompt

    async def cleanup(self) -> None:
        """Close internal clients and reset the module-level service reference.

        Attempts to close the Qdrant KB client and, if present, the DLF client. Always resets the module-level `_service` reference to `None` so the service can be recreated.
        """
        try:
            await self.qdrant_kb_client.close()
            if self.dlf_client is not None:
                await self.dlf_client.close()
        finally:
            global _service
            _service = None

    def get_prompt_versions(self) -> dict[str, int | None]:
        """Return a dictionary mapping prompt names to their version numbers.

        Returns:
            dict[str, int | None]: A dictionary where keys are prompt names and values are their corresponding version numbers (or None if not applicable).
        """
        prompts: dict[str, int | None] = {}
        if self.settings.answer.agent_prompt.type == "langfuse":
            prompts["agent"] = self.agent_prompt_version

        if self.settings.answer.format_prompt.type == "langfuse":
            prompts["format"] = self.format_prompt_version

        if self.judge_handler is not None and self.settings.answer.judge.prompt.type == "langfuse":
            prompts["judge"] = self.judge_prompt_version

        return prompts


_service: AnswerService | None = None


def get_answer_service(settings: ZammadAISettings | None = None) -> AnswerService:
    """Get or create the shared AnswerService instance.

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
