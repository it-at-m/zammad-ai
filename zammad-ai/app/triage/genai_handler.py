"""GenAI handler for triage operations.

This module contains all LangChain/GenAI logic for the triage process.
All chains are constructed during initialization for efficient invocation.
"""

from logging import Logger
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableSequence
from langfuse import observe

from app.core.settings.genai import GenAISettings
from app.models.triage import (
    CategorizationResult,
    DaysSinceRequestResponse,
    ProcessingIdResponse,
)
from app.observe.observer import LangfuseClient
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.genai_handler")

T = TypeVar("T")


class GenAIHandler:
    """Handles all GenAI/LangChain operations for triage.

    Constructs all chains during initialization and provides clean async methods
    for invoking them with observability support.
    """

    def __init__(self, genai_settings: GenAISettings, prompts: dict[str, str]) -> None:
        """
        Initialize the GenAIHandler, configure the chat model, and pre-build runnable chains for triage operations.
        
        Parameters:
            genai_settings (GenAISettings): GenAI configuration including `sdk`, model name, temperature, max_retries, and optional `reasoning_effort`.
            prompts (dict[str, str]): Mapping of prompt templates required by the handler. Expected keys:
                - "role"
                - "categories"
                - "examples"
                - "days_since_request"
                - "processing_id"
        
        Raises:
            ValueError: If an unsupported GenAI SDK is specified.
        """
        self.prompts = prompts
        self.langfuse_client = LangfuseClient()

        # Initialize LLM based on configured SDK
        match genai_settings.sdk:
            case "openai":
                from langchain_openai import ChatOpenAI

                self.chat_model = ChatOpenAI(
                    model=genai_settings.chat_model,  # type: ignore
                    temperature=genai_settings.temperature,
                    max_retries=genai_settings.max_retries,
                    reasoning={
                        "effort": genai_settings.reasoning_effort,
                        "summary": "detailed",
                    }
                    if genai_settings.reasoning_effort is not None
                    else None,
                    store=False,
                )
            case _:
                raise ValueError(f"Unsupported GenAI SDK: {genai_settings.sdk}")

        # Pre-construct chains for each operation
        self._build_chains()

        logger.info("GenAI handler initialized successfully")

    def _build_chains(self) -> None:
        """
        Construct reusable LangChain runnable sequences for triage operations.
        
        Builds and assigns three instance-level chains:
        - category_chain: categorization prompt using prompts["categories"] that produces a CategorizationResult.
        - days_since_request_chain: extraction prompt using prompts["days_since_request"] that produces a DaysSinceRequestResponse.
        - processing_id_chain: extraction prompt using prompts["processing_id"] that produces a ProcessingIdResponse.
        """
        # Category prediction chain
        self.category_chain = RunnableSequence(
            ChatPromptTemplate(
                messages=[
                    ("system", self.prompts.get("categories", "")),
                    ("user", "{text}"),
                ]
            ),
            self.chat_model.with_structured_output(schema=CategorizationResult, strict=True),
        )

        # Days since request extraction chain
        self.days_since_request_chain = RunnableSequence(
            ChatPromptTemplate(
                messages=[
                    ("system", self.prompts.get("days_since_request", "")),
                    ("user", "{text}"),
                ]
            ),
            self.chat_model.with_structured_output(schema=DaysSinceRequestResponse, strict=True),
        )

        # Processing ID extraction chain
        self.processing_id_chain = RunnableSequence(
            ChatPromptTemplate(
                messages=[
                    ("system", self.prompts.get("processing_id", "")),
                    ("user", "{text}"),
                ]
            ),
            self.chat_model.with_structured_output(schema=ProcessingIdResponse, strict=True),
        )

    @observe(name="Zammad-AI Triage Predict Category", as_type="span")
    async def predict_category(
        self,
        input: dict,
        session_id: str | None = None,
    ) -> CategorizationResult:
        """
        Predicts the category for the provided message and returns classification details.
        
        Parameters:
            input (dict): Payload containing at least the "text" key with the message to categorize; may include additional context.
            session_id (str | None): Optional Langfuse session ID used for tracing.
        
        Returns:
            CategorizationResult: Predicted category, explanatory reasoning, and confidence score.
        """
        return await self._invoke_chain(
            chain=self.category_chain,
            input=input,
            session_id=session_id,
        )

    @observe(name="Zammad-AI Triage Days Since Request", as_type="span")
    async def extract_days_since_request(
        self,
        input: dict,
        session_id: str | None = None,
    ) -> DaysSinceRequestResponse:
        """
        Extract the number of days since a request from the provided input.
        
        Parameters:
            input (dict): Dictionary with keys:
                - "text": Message text to extract the date/reference from.
                - "today": Current date as a string in YYYY-MM-DD format.
            session_id (str | None): Optional Langfuse session ID used for tracing.
        
        Returns:
            DaysSinceRequestResponse: Response containing the extracted days value.
        """
        return await self._invoke_chain(
            chain=self.days_since_request_chain,
            input=input,
            session_id=session_id,
        )

    @observe(name="Zammad-AI Triage Processing ID", as_type="span")
    async def extract_processing_id(
        self,
        input: dict,
        session_id: str | None = None,
    ) -> ProcessingIdResponse:
        """
        Extract the processing ID from the provided input message.
        
        Parameters:
            input (dict): Input payload containing:
                - "text": Message text to extract the ID from.
                - "condition": Condition string used to match or validate the ID.
            session_id (str | None): Optional Langfuse session ID used for tracing.
        
        Returns:
            ProcessingIdResponse: Response object containing the extracted processing ID.
        """
        return await self._invoke_chain(
            chain=self.processing_id_chain,
            input=input,
            session_id=session_id,
        )

    async def _invoke_chain(
        self,
        chain: RunnableSequence[Any, T],
        input: dict,
        session_id: str | None = None,
    ) -> T:
        """
        Invoke a pre-built RunnableSequence and associate the call with a Langfuse session trace.
        
        Parameters:
            chain (RunnableSequence[Any, T]): The pre-built chain to execute.
            input (dict): Input payload passed to the chain.
            session_id (str | None): Optional Langfuse session ID to use for tracing; a new session ID is generated if omitted.
        
        Returns:
            T: The chain's output.
        """
        if session_id is None:
            session_id = self.langfuse_client.generate_session_id()

        self.langfuse_client.langfuse.update_current_trace(session_id=session_id)
        config: RunnableConfig = self.langfuse_client.build_config(session_id=session_id)

        response: T = await chain.ainvoke(input=input, config=config)
        return response