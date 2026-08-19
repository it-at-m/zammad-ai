"""GenAI handler for all LangChain-based triage model interactions.

This module centralizes language-model invocation for triage-related workflows.
It validates prompt configuration, builds durable structured-output chains, and
executes calls with Langfuse tracing metadata.
"""

from logging import Logger
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langfuse import observe, propagate_attributes
from langfuse.model import PromptClient

from app.errors import classify_provider_error
from app.models.triage import CategorizationResult, DaysSinceRequestResponse, ProcessingIdResponse
from app.observe import LangfuseClient
from app.settings.genai import GenAIProviderSettings
from app.utils.genai_provider import get_chat_model
from app.utils.langchain import extract_structured_response, with_recursion_limit
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.genai_handler")

T = TypeVar("T")

StructuredAgent = Any


class GenAIHandler:
    """Execute triage-related GenAI operations via reusable LangChain chains.

    The handler validates required prompts at initialization time, configures the
    selected chat model, and pre-builds structured-output chains for each triage
    operation to avoid rebuilding chain objects on every request.
    """

    REQUIRED_PROMPT_KEYS = {"triage", "days_since_request", "processing_id"}

    def __init__(
        self,
        genai_settings: GenAIProviderSettings,
        prompts: dict[str, str],
        categories_langfuse_prompt: PromptClient | None = None,
    ) -> None:
        """Initialize model configuration and durable operation chains.

        Args:
            genai_settings: GenAI settings containing SDK, model, retry, and
                reasoning configuration.
            prompts: Mapping of prompt keys to prompt template strings.
            categories_langfuse_prompt: Optional Langfuse prompt reference used to
                link the categorization generation to a prompt version in Langfuse.

        Raises:
            ValueError: If prompts are missing/empty or the configured SDK is
                not supported.
        """
        # TODO: Refactor langfuse client as optional argument, if not passed there is no tracing and no handler is passed to the chains
        self.langfuse_client = LangfuseClient()
        self.categories_langfuse_prompt = categories_langfuse_prompt

        # Validate that prompts are properly configured
        if not prompts:
            error_msg = "Prompts dictionary cannot be empty."
            logger.error(error_msg)
            raise ValueError(error_msg)

        missing_keys = self.REQUIRED_PROMPT_KEYS - set(prompts)
        if missing_keys:
            error_msg = f"Missing required prompt keys: {', '.join(sorted(missing_keys))}."
            logger.error(error_msg)
            raise ValueError(error_msg)

        empty_required_keys: list[str] = [
            key
            for key in sorted(self.REQUIRED_PROMPT_KEYS)
            if not isinstance(prompts.get(key), str) or not prompts[key].strip()
        ]
        if empty_required_keys:
            error_msg = (
                "Empty prompt values for required keys: "
                f"{', '.join(empty_required_keys)}. "
                "Required system prompts must be non-empty strings."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Initialize LLM via provider factory.
        self.chat_model = get_chat_model(genai_settings, "triage")

        # Build durable chains once so each operation reuses the same chain instance.
        self._categorization_chain = self._build_chain(
            prompt=prompts["triage"],
            output_schema=CategorizationResult,
            langfuse_prompt=self.categories_langfuse_prompt,
        )
        self._days_since_request_chain = self._build_chain(
            prompt=prompts["days_since_request"], output_schema=DaysSinceRequestResponse
        )
        self._processing_id_chain = self._build_chain(
            prompt=prompts["processing_id"], output_schema=ProcessingIdResponse
        )

        logger.info("GenAI handler initialized successfully")

    @observe(as_type="span")
    async def categorize_ticket(
        self,
        *,
        message: str,
        role_description: str,
        categories: list[Any],
        categories_prompt: str,
        examples: str,
        session_id: str | None = None,
    ) -> CategorizationResult:
        """Categorize a ticket message into one of the configured categories.

        Args:
            message: Incoming ticket message text.
            role_description: Role description used by the categorization prompt.
            categories: Available categories passed into the prompt context.
            categories_prompt: Additional category-specific prompt fragment.
            examples: In-context examples for the categorization prompt.
            session_id: Optional trace session id.

        Returns:
            Structured categorization result from the model.
        """
        session_id, config = self._build_runnable_config(session_id=session_id)

        try:
            logger.info("Starting ToolStrategy categorization invocation.")
            with propagate_attributes(session_id=session_id):
                response: CategorizationResult = await self._ainvoke_structured_agent(
                    structured_agent=self._categorization_chain,
                    input={
                        "text": message,
                        "role_description": role_description,
                        "categories": categories,
                        "categories_prompt": categories_prompt,
                        "examples": examples,
                    },
                    config=config,
                    expected_type=CategorizationResult,
                )
            logger.info("Finished ToolStrategy categorization invocation.")
            return response
        except Exception as e:
            logger.error("Error during GenAI invocation for categorization", exc_info=True)
            classified = classify_provider_error(e)
            raise classified from e

    @observe(as_type="span")
    async def extract_days_since_request(
        self, *, message: str, today: str, session_id: str | None = None
    ) -> DaysSinceRequestResponse:
        """Extract days-since-request information from a ticket message.

        Args:
            message: Incoming ticket message text.
            today: Current date representation used for date-relative extraction.
            session_id: Optional trace session id.

        Returns:
            Structured response containing extracted day offset information.
        """
        session_id, config = self._build_runnable_config(session_id=session_id)

        try:
            logger.info("Starting ToolStrategy days-since-request invocation.")
            with propagate_attributes(session_id=session_id):
                response: DaysSinceRequestResponse = await self._ainvoke_structured_agent(
                    structured_agent=self._days_since_request_chain,
                    input={
                        "text": message,
                        "today": today,
                    },
                    config=config,
                    expected_type=DaysSinceRequestResponse,
                )
            logger.info("Finished ToolStrategy days-since-request invocation.")
            return response
        except Exception as e:
            logger.error("Error during GenAI invocation for days since request extraction", exc_info=True)
            classified = classify_provider_error(e)
            raise classified from e

    @observe(as_type="span")
    async def extract_processing_id(self, *, message: str, session_id: str | None = None) -> ProcessingIdResponse:
        """Extract a processing identifier from a ticket message.

        Args:
            message: Incoming ticket message text.
            session_id: Optional trace session id.

        Returns:
            Structured response containing the extracted processing id.
        """
        session_id, config = self._build_runnable_config(session_id=session_id)

        try:
            logger.info("Starting ToolStrategy processing-id invocation.")
            with propagate_attributes(session_id=session_id):
                response: ProcessingIdResponse = await self._ainvoke_structured_agent(
                    structured_agent=self._processing_id_chain,
                    input={
                        "text": message,
                    },
                    config=config,
                    expected_type=ProcessingIdResponse,
                )
            logger.info("Finished ToolStrategy processing-id invocation.")
            return response
        except Exception as e:
            logger.error("Error during GenAI invocation for processing id extraction", exc_info=True)
            classified = classify_provider_error(e)
            raise classified from e

    def _build_chain(
        self,
        prompt: str,
        output_schema: type[T],
        langfuse_prompt: PromptClient | None = None,
    ) -> StructuredAgent:
        """Create a reusable ToolStrategy agent for one structured prompt.

        Args:
            prompt: The prompt to use.
            output_schema: Pydantic model used for strict structured output parsing.
            langfuse_prompt: Optional Langfuse prompt reference to attach to the prompt runnable.

        Returns:
            A prompt template and agent that return a validated structured response.

        Raises:
            KeyError: If prompt_key is not present in configured prompts.
        """
        if not prompt.strip():
            raise ValueError("Prompt template cannot be empty.")

        prompt_template = ChatPromptTemplate(
            messages=[
                ("system", prompt),
                ("user", "{text}"),
            ]
        )

        if langfuse_prompt is not None:
            prompt_template = prompt_template.with_config(metadata={"langfuse_prompt": langfuse_prompt})

        agent = create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=(
                f"You must finish by calling exactly one structured response tool for the "
                f"{output_schema.__name__} schema. Do not answer with free text, markdown, or raw JSON."
            ),
            response_format=ToolStrategy(
                schema=output_schema,
                tool_message_content="Structured triage response has been generated.",
            ),
        )
        return prompt_template | RunnableLambda(lambda prompt_value: {"messages": prompt_value.to_messages()}) | agent

    async def _ainvoke_structured_agent(
        self,
        *,
        structured_agent: StructuredAgent,
        input: dict[str, Any],
        config: RunnableConfig,
        expected_type: type[T],
    ) -> T:
        """Render a prompt, invoke a ToolStrategy agent, and return its structured response."""
        agent_result: dict[str, Any] = await structured_agent.ainvoke(
            input=input,
            config=with_recursion_limit(config),
        )
        return extract_structured_response(agent_result, expected_type)

    def _build_runnable_config(self, session_id: str | None) -> tuple[str, RunnableConfig]:
        """Resolve session id and build runnable tracing configuration.

        Args:
            session_id: Optional external session identifier.

        Returns:
            Tuple of resolved session id and LangChain runnable configuration.
        """
        resolved_session_id: str | None = session_id.strip() if session_id is not None else None
        if not resolved_session_id:
            resolved_session_id = self.langfuse_client.generate_session_id()

        config: RunnableConfig = self.langfuse_client.build_config(session_id=resolved_session_id)
        return resolved_session_id, config
