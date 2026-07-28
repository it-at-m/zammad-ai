"""LangChain agent wiring for answer generation."""

from logging import Logger
from typing import Any

from langchain.agents import create_agent
from langchain.tools import BaseTool, ToolException, ToolRuntime, tool
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.models.answer import StructuredAgentResponse
from app.settings import GenAISettings
from app.settings.answer import LawToolSettings
from app.utils.logging import getLogger

from .dlf import DLFClient, DLFDocument, DLFError, SearchDLFInput
from .knowledgebase import QdrantKBClient, QdrantKBError, RetrieveDocumentsKBOutput, SearchQdrantKBInput
from .laws import build_law_tool_name

logger: Logger = getLogger("zammad-ai.answer.agent")


class AgentContext(BaseModel):
    """Runtime context passed into the answer agent tools."""

    qdrant_kb_client: QdrantKBClient
    dlf_client: DLFClient | None

    model_config = {
        "arbitrary_types_allowed": True,  # Allow arbitrary types like QdrantKBClient and DLFClient
    }


@tool(
    "search_website",
    description="Search the city of munich website including all public service descriptions and information articles for relevant documents",
    args_schema=SearchDLFInput,
    parse_docstring=False,
    response_format="content",
)
async def search_dlf(runtime: ToolRuntime[AgentContext], query: str) -> list[DLFDocument]:
    """Search the Munich city (DLF) site using the runtime's DLF client and return retrieved documents.

    Parameters:
        query (str): Query string to send to the DLF site.

    Returns:
        list[DLFDocument]: Documents retrieved from the DLF client matching the query.

    Raises:
        ToolException: If the DLF client is not initialized in the runtime context or if an HTTP error occurs during retrieval.
    """
    dlf_client: DLFClient | None = runtime.context.dlf_client

    if dlf_client is None:
        logger.error("DLF client is not initialized in the agent context.")
        raise ToolException("Failed to search the munich city website. Please try other tools for now.")

    if len(query) > dlf_client.query_max_length:
        logger.warning(
            f"Query length exceeds maximum allowed characters of {dlf_client.query_max_length}. Truncating query."
        )
        query = query[: dlf_client.query_max_length]

    try:
        dlf_docs: list[DLFDocument] = await dlf_client.retrieve_documents(query=query)
        return dlf_docs
    except DLFError:
        logger.error("HTTP error while searching DLF", exc_info=True)
        raise ToolException("Failed to search the munich city website. Please try other tools for now.")


@tool(
    "search_internal_knowledgebase",
    description="Retrieve relevant documents for a query from the knowledge base.",
    args_schema=SearchQdrantKBInput,
    parse_docstring=False,
    response_format="content",
)
async def search_knowledgebase(
    runtime: ToolRuntime[AgentContext],
    query: str,
    num_documents: int = 5,
    offset: int = 0,
) -> RetrieveDocumentsKBOutput:
    """Retrieve relevant documents from the knowledge base for a given query.

    Parameters:
        runtime (ToolRuntime[AgentContext]): Tool runtime whose context provides a QdrantKBClient.
        query (str): Query text to search for.
        num_documents (int): Maximum number of documents to return.
        offset (int): Number of top results to skip before collecting documents.

    Returns:
        RetrieveDocumentsKBOutput: Contains `documents_with_relevance_score`, a list of `(Document, float)` tuples ordered by relevance.

    Raises:
        ToolException: If the knowledge base retrieval fails.
    """
    qdrant_client: QdrantKBClient = runtime.context.qdrant_kb_client
    try:
        relevant_documents_with_scores: list[tuple[Document, float]] = await qdrant_client.asearch_documents(
            query=query,
            k=num_documents,
            offset=offset,
        )
        return RetrieveDocumentsKBOutput(documents_with_relevance_score=relevant_documents_with_scores)
    except QdrantKBError as e:
        logger.error("Error retrieving documents from Qdrant", exc_info=True)
        raise ToolException("Failed to retrieve documents from Knowledge Base") from e


def build_law_tool(law: LawToolSettings) -> BaseTool:
    """Create a retrieval tool scoped to one configured law."""
    law_id = law.id
    law_name = law.name
    tool_name = build_law_tool_name(law_id)

    @tool(
        tool_name,
        description=(
            f"Retrieve relevant paragraphs and annexes from the indexed law '{law_name}' "
            f"(law_id: {law_id}). Use this when additional legal information from this law is needed."
        ),
        args_schema=SearchQdrantKBInput,
        parse_docstring=False,
        response_format="content",
    )
    async def search_law(
        runtime: ToolRuntime[AgentContext],
        query: str,
        num_documents: int = 5,
        offset: int = 0,
    ) -> RetrieveDocumentsKBOutput:
        qdrant_client: QdrantKBClient = runtime.context.qdrant_kb_client
        try:
            relevant_documents_with_scores: list[tuple[Document, float]] = await qdrant_client.asearch_law_documents(
                law_id=law_id,
                query=query,
                k=num_documents,
                offset=offset,
            )
            return RetrieveDocumentsKBOutput(documents_with_relevance_score=relevant_documents_with_scores)
        except QdrantKBError as e:
            logger.error("Error retrieving law documents from Qdrant", exc_info=True)
            raise ToolException(f"Failed to retrieve documents from {law_name}") from e

    return search_law


def build_agent(
    genai_settings: GenAISettings,
    system_prompt: str,
    dlf_enabled: bool = True,
    laws: list[LawToolSettings] | None = None,
) -> Any:
    """Constructs a LangChain agent configured for Zammad AI Answer using the provided model settings, system prompt, and tools.

    Parameters:
        genai_settings (GenAISettings): Model and generation parameters used to create the chat model.
        system_prompt (str): System prompt supplied to the agent.
        dlf_enabled (bool): If True, include the DLF website search tool in the agent's toolset.
        laws (list[LawToolSettings] | None): Indexed laws to expose as dedicated retrieval tools.

    Returns:
        CompiledStateGraph[AgentState[StructuredAgentResponse], AgentContext, AgentState, AgentState[StructuredAgentResponse]]:
            A compiled agent configured with a ChatOpenAI model, the supplied system prompt, the knowledge-base search tool (and optionally the DLF tool), producing StructuredAgentResponse outputs and using AgentContext for runtime clients.
    """
    # Build the chat model
    chat_model = ChatOpenAI(
        model=genai_settings.answer_model or genai_settings.chat_model,
        temperature=genai_settings.answer_temperature,
        max_retries=genai_settings.max_retries,
        reasoning=genai_settings.answer_reasoning_config,
    )

    # Configure the tools
    available_tools: list[BaseTool] = [
        search_knowledgebase,
    ]
    if dlf_enabled:
        available_tools.append(search_dlf)
    for law in laws or []:
        available_tools.append(build_law_tool(law))

    # Create the agent via the factory method
    agent: Any = create_agent(
        model=chat_model,
        system_prompt=system_prompt,
        tools=available_tools,
        response_format=StructuredAgentResponse,
        context_schema=AgentContext,
    )

    return agent
