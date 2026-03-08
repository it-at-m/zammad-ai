from logging import Logger

from httpx import HTTPError
from langchain.agents import create_agent
from langchain.agents.middleware.types import AgentState, _InputAgentState, _OutputAgentState
from langchain.tools import BaseTool, ToolException, ToolRuntime, tool
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.models.answer import StructuredAgentResponse
from app.settings import GenAISettings
from app.utils.logging import getLogger
from app.utils.templating import render_template_string

from .dlf import DLFClient, DLFDocument
from .knowledgebase import QdrantKBClient, QdrantKBError, RetrieveDocumentsKBOutput, SearchQdrantKBInput

logger: Logger = getLogger("zammad-ai.answer.agent")


class AgentContext(BaseModel):
    qdrant_kb_client: QdrantKBClient
    dlf_client: DLFClient | None

    model_config = {
        "arbitrary_types_allowed": True,  # Allow arbitrary types like QdrantKBClient and DLFClient
    }


@tool(
    "search_website",
    description="Search the city of munich website including all public service descriptions and information articles for relevant documents",
    # args_schema=SearchDLFInput,
    parse_docstring=False,
    response_format="content",
)
async def search_dlf(runtime: ToolRuntime[AgentContext], query: str) -> list[DLFDocument]:
    if runtime.context.dlf_client is None:
        logger.error("DLF client is not initialized in the agent context.")
        raise ToolException("Failed to search the munich city website. Please try other tools for now.")
    dlf_client: DLFClient = runtime.context.dlf_client
    try:
        dlf_docs: list[DLFDocument] = await dlf_client.retrieve_documents(query=query)
        return dlf_docs
    except HTTPError as e:
        logger.error("HTTP error while searching DLF", exc_info=e)
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
    """
    Retrieve relevant documents based on a query.

    Args:
        query (str): The search query string.

    Returns:
        RetrieveDocumentsKBOutput: A dictionary containing lists of retrieved documents.

    Raises:
        ToolException: If the retrieval process fails.
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
        logger.error("Error retrieving documents from Qdrant", exc_info=e)
        raise ToolException("Failed to retrieve documents from Knowledge Base") from e


def build_agent(
    genai_settings: GenAISettings,
    system_prompt: str,
    dlf_enabled: bool = True,
) -> CompiledStateGraph[AgentState[StructuredAgentResponse], AgentContext, _InputAgentState, _OutputAgentState[StructuredAgentResponse]]:  # type: ignore
    """Build and return the Zammad AI Answer agent."""

    # Build the chat model
    chat_model = ChatOpenAI(
        model_name=genai_settings.answer_model or genai_settings.chat_model,
        temperature=genai_settings.temperature,
        max_retries=genai_settings.max_retries,
    )

    # Configure the tools
    available_tools: list[BaseTool] = [
        search_knowledgebase,
    ]
    if dlf_enabled:
        available_tools.append(search_dlf)

    # Render system prompt using Jinja2
    search_strategy = (
        "Start by searching the knowledge base for standard procedures. "
        "If you cannot find sufficient information, query the DLF (Digital Driver's License File) if available."
    )
    rendered_system_prompt = render_template_string(system_prompt, tools=available_tools, search_strategy=search_strategy)

    # Create the agent via the factory method
    agent: CompiledStateGraph[
        AgentState[StructuredAgentResponse], AgentContext, _InputAgentState, _OutputAgentState[StructuredAgentResponse]  # type: ignore
    ] = create_agent(
        model=chat_model,
        system_prompt=rendered_system_prompt,
        tools=available_tools,
        response_format=StructuredAgentResponse,
        context_schema=AgentContext,
    )

    return agent
