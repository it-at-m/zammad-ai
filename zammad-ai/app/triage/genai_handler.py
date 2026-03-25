"""GenAI handler for all LangChain-based triage model interactions.

This module centralizes language-model invocation for triage-related workflows.
It validates prompt configuration, builds durable structured-output chains, and
executes calls with Langfuse tracing metadata.
"""

from logging import Logger
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableSequence
from langfuse import observe, propagate_attributes

from app.models.triage import CategorizationResult, DaysSinceRequestResponse, ProcessingIdResponse
from app.observe import LangfuseClient
from app.settings.genai import GenAISettings
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.genai_handler")

T = TypeVar("T")


class GenAIError(Exception):
    """Raised when a GenAI operation fails."""


class GenAIHandler:
    """Execute triage-related GenAI operations via reusable LangChain chains.

    The handler validates required prompts at initialization time, configures the
    selected chat model, and pre-builds structured-output chains for each triage
    operation to avoid rebuilding chain objects on every request.
    """

    REQUIRED_PROMPT_KEYS = {"triage", "days_since_request", "processing_id"}

    def __init__(self, genai_settings: GenAISettings, prompts: dict[str, str]) -> None:
        """Initialize model configuration and durable operation chains.

        Args:
            genai_settings: GenAI settings containing SDK, model, retry, and
                reasoning configuration.
            prompts: Mapping of prompt keys to prompt template strings.

        Raises:
            ValueError: If prompts are missing/empty or the configured SDK is
                not supported.
        """
        # TODO: Refactor langfuse client as optional argument, if not passed there is no tracing and no handler is passed to the chains
        self.langfuse_client = LangfuseClient()

        # Validate that prompts are properly configured
        if not prompts:
            error_msg = "Prompts dictionary cannot be empty."
            logger.error(error_msg)
            raise ValueError(error_msg)

        empty_keys: list[str] = [key for key, value in prompts.items() if not isinstance(value, str) or not value.strip()]
        if empty_keys:
            error_msg = f"Empty prompt values for keys: {', '.join(empty_keys)}. All prompts must be non-empty strings."
            logger.error(error_msg)
            raise ValueError(error_msg)

        missing_keys = self.REQUIRED_PROMPT_KEYS - set(prompts)
        if missing_keys:
            error_msg = f"Missing required prompt keys: {', '.join(sorted(missing_keys))}."
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Initialize LLM based on configured SDK
        match genai_settings.sdk:
            case "openai":
                from langchain_openai import ChatOpenAI

                self.chat_model = ChatOpenAI(
                    model_name=genai_settings.chat_model,
                    temperature=genai_settings.temperature,
                    max_retries=genai_settings.max_retries,
                    reasoning=genai_settings.reasoning_config,
                    store=genai_settings.store,
                )
            case _:
                raise ValueError(f"Unsupported GenAI SDK: {genai_settings.sdk}")

        # Build durable chains once so each operation reuses the same chain instance.
        self._categorization_chain = self._build_chain(prompt=prompts["triage"], output_schema=CategorizationResult)
        self._days_since_request_chain = self._build_chain(prompt=prompts["days_since_request"], output_schema=DaysSinceRequestResponse)
        self._processing_id_chain = self._build_chain(prompt=prompts["processing_id"], output_schema=ProcessingIdResponse)

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
            with propagate_attributes(session_id=session_id):
                response: CategorizationResult = await self._categorization_chain.ainvoke(
                    input={
                        "text": message,
                        "role_description": role_description,
                        "categories": categories,
                        "categories_prompt": categories_prompt,
                        "examples": examples,
                    },
                    config=config,
                )
            return response
        except Exception as e:
            logger.error("Error during GenAI invocation for categorization", exc_info=True)
            raise GenAIError("GenAI operation failed") from e

    @observe(as_type="span")
    async def extract_days_since_request(self, *, message: str, today: str, session_id: str | None = None) -> DaysSinceRequestResponse:
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
            with propagate_attributes(session_id=session_id):
                response: DaysSinceRequestResponse = await self._days_since_request_chain.ainvoke(
                    input={
                        "text": message,
                        "today": today,
                    },
                    config=config,
                )
            return response
        except Exception as e:
            logger.error("Error during GenAI invocation for days since request extraction", exc_info=True)
            raise GenAIError("GenAI operation failed") from e

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
            with propagate_attributes(session_id=session_id):
                response: ProcessingIdResponse = await self._processing_id_chain.ainvoke(
                    input={
                        "text": message,
                    },
                    config=config,
                )
            return response
        except Exception as e:
            logger.error("Error during GenAI invocation for processing id extraction", exc_info=True)
            raise GenAIError("GenAI operation failed") from e

    def _build_chain(self, prompt: str, output_schema: type[T] | None = None) -> RunnableSequence[Any, T]:
        """Create a reusable structured-output chain for one prompt.

        Args:
            prompt: The prompt to use.
            output_schema: Pydantic model used for strict structured output parsing.

        Returns:
            A runnable sequence that accepts invocation input and returns a value
            parsed as the provided schema.

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

        return RunnableSequence(
            prompt_template,
            self.chat_model.with_structured_output(schema=output_schema, strict=True) if output_schema else self.chat_model,
        )

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
