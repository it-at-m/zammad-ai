"""GenAI handler for language model operations.

This module contains all LangChain/GenAI logic for invoking language models.
Chains are constructed on-demand based on prompt keys and optional response schemas.
"""

from logging import Logger
from typing import Any, TypeVar, overload

from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableSequence
from langfuse import observe

from app.observe import LangfuseClient
from app.settings.genai import GenAISettings
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.genai_handler")

T = TypeVar("T")


class GenAIError(Exception):
    """Exception raised for errors in the GenAI handler."""


class GenAIHandler:
    """Handles all GenAI/LangChain operations for language model invocation.

    Dynamically builds chains based on provided prompts and response schemas.
    Provides async methods for invoking chains with observability support.
    """

    def __init__(self, genai_settings: GenAISettings, prompts: dict[str, str]) -> None:
        """
        Initialize the GenAIHandler and configure the chat model.

        Parameters:
            genai_settings (GenAISettings): GenAI configuration including `sdk`, model name, temperature, max_retries.
            prompts (dict[str, str]): Mapping of prompt keys to their template strings. All values must be non-empty strings.

        Raises:
            ValueError: If an unsupported GenAI SDK is specified or if prompts is empty/contains empty values.
        """
        self.prompts = prompts
        self._chains: dict[str, RunnableSequence[Any, Any]] = {}  # Cache for built chains
        # TODO: Refactor langfuse client as optional argument, if not passed there is no tracing and no handler is passed to the chains
        self.langfuse_client = LangfuseClient()

        # Validate that prompts are properly configured
        self._validate_prompts()

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

        logger.info("GenAI handler initialized successfully")

    def _validate_prompts(self) -> None:
        """
        Validate that prompts dictionary is properly configured.

        Ensures that:
        - The prompts dictionary is not empty
        - All prompt values are non-empty strings

        Raises:
            ValueError: If prompts is empty or contains empty values.
        """
        if not self.prompts:
            error_msg = "Prompts dictionary cannot be empty."
            logger.error(error_msg)
            raise ValueError(error_msg)

        empty_keys = [key for key, value in self.prompts.items() if not value]
        if empty_keys:
            error_msg = f"Empty prompt values for keys: {', '.join(empty_keys)}. All prompts must be non-empty strings."
            logger.error(error_msg)
            raise ValueError(error_msg)

    def _build_or_get_chain(self, prompt_key: str, schema: type[T] | None = None) -> RunnableSequence[Any, T | dict[str, Any]]:
        """
        Build or retrieve a cached chain for the given prompt key and optional schema.

        Chains are cached with a key combining the prompt_key and schema (if provided) to support
        the same prompt being used with different output schemas.

        Parameters:
            prompt_key (str): The key in self.prompts identifying which prompt to use.
            schema (type[T] | None): Optional Pydantic schema for structured output.

        Returns:
            RunnableSequence: A chain ready to invoke with input data.
        """
        cache_key = f"{prompt_key}_{schema.__name__ if schema else 'raw'}"

        if cache_key not in self._chains:
            prompt_template = ChatPromptTemplate.from_messages(
                [
                    SystemMessagePromptTemplate.from_template(self.prompts[prompt_key], template_format="jinja2"),
                    HumanMessagePromptTemplate.from_template("{{ text }}", template_format="jinja2"),
                ]
            )

            if schema is not None:
                chain = RunnableSequence(
                    prompt_template,
                    self.chat_model.with_structured_output(schema=schema, strict=True),
                )
            else:
                chain = RunnableSequence(prompt_template, self.chat_model)

            self._chains[cache_key] = chain

        return self._chains[cache_key]

    @overload
    async def invoke(
        self,
        prompt_key: str,
        input: dict,
        *,
        session_id: str | None = None,
        schema: type[T],
    ) -> T: ...

    @overload
    async def invoke(
        self,
        prompt_key: str,
        input: dict,
        *,
        session_id: str | None = None,
        schema: None = None,
    ) -> dict[str, Any]: ...

    @observe(as_type="span")
    async def invoke(
        self,
        prompt_key: str,
        input: dict,
        *,
        session_id: str | None = None,
        schema: type[T] | None = None,
    ) -> T | dict[str, Any]:
        """
        Invoke the language model using a specified prompt and optional output schema.

        Chains are cached based on prompt_key and schema, so repeated invocations with the same
        prompt_key/schema combination reuse the built chain without rebuilding.

        Parameters:
            prompt_key (str): The key in self.prompts identifying which prompt to use.
            input (dict): Input variables for the prompt template (must include "text" key).
            session_id (str | None): Optional Langfuse session ID for tracing. Generated if not provided.
            schema (type[T] | None): Optional Pydantic schema for structured output. If provided, model output
                will be parsed into this schema. If None, raw model output is returned.

        Returns:
            T | dict[str, Any]: Either a structured object matching the schema (if provided) or raw dict output.

        Raises:
            GenAIError: If the language model invocation fails.
            KeyError: If the prompt_key doesn't exist in prompts.
        """
        if prompt_key not in self.prompts:
            error_msg = f"Prompt key '{prompt_key}' not found in prompts dictionary."
            logger.error(error_msg)
            raise KeyError(error_msg)

        if session_id is None:
            session_id = self.langfuse_client.generate_session_id()

        self.langfuse_client.langfuse.update_current_trace(session_id=session_id)
        config: RunnableConfig = self.langfuse_client.build_config(session_id=session_id)

        try:
            chain = self._build_or_get_chain(prompt_key=prompt_key, schema=schema)
            response: T | dict[str, Any] = await chain.ainvoke(input=input, config=config)
            return response
        except Exception as e:
            logger.error("Error during GenAI invocation", exc_info=True)
            raise GenAIError("GenAI operation failed") from e
