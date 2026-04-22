"""Qdrant knowledge-base client and retrieval helpers."""

from logging import Logger
from uuid import NAMESPACE_DNS, UUID, uuid5

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_qdrant import QdrantVectorStore
from pydantic import BaseModel, Field, NonNegativeInt, PositiveInt
from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http.exceptions import ApiException
from qdrant_client.http.models import CollectionInfo

from app.settings import GenAISettings, QdrantSettings
from app.utils.logging import getLogger

logger: Logger = getLogger("zammad-ai.answer.knowledgebase")

# Create a consistent namespace UUID for generating vector IDs based on content
ZAMMAD_AI_NAMESPACE: UUID = uuid5(
    namespace=NAMESPACE_DNS,
    name="zammad-ai.muenchen.de",
)


class SearchQdrantKBInput(BaseModel):
    """Validated input for knowledge-base search queries."""

    query: str = Field(
        description="The search query string; should be concise and focused on the information needed; maximum length is 200 characters (~ 20 words).",
        max_length=200,
    )
    num_documents: PositiveInt = Field(
        default=5,
        description="The number of relevant documents to retrieve; should be a positive integer; default is 5.",
    )
    offset: NonNegativeInt = Field(
        default=0,
        description="The number of top relevant documents to skip for pagination; should be a non-negative integer; default is 0. Good for retrieving the next set of results in subsequent calls with the same query.",
    )


class RetrieveDocumentsKBOutput(BaseModel):
    """Knowledge-base search results with relevance scores."""

    documents_with_relevance_score: list[tuple[Document, float]] = Field(
        description="A list of tuples containing retrieved documents and their corresponding relevance scores between 0 and 1; the list is ordered by relevance score in descending order.",
    )


class QdrantKBError(Exception):
    """Custom exception for Qdrant-related errors."""

    ...


class QdrantKBClient:
    """Wrapper around Qdrant client to handle vector storage and retrieval."""

    def __init__(self, qdrant_settings: QdrantSettings, genai_settings: GenAISettings) -> None:
        # Create logger for QdrantClient
        """Initialize the QdrantKBClient, configure Qdrant clients, embeddings, vector store, and retriever.

        Parameters:
            qdrant_settings (QdrantSettings): Configuration for Qdrant connection, collection, vector dimensions, vector name, timeout, and retrieval defaults.
            genai_settings (GenAISettings): Configuration for the embedding provider (SDK, embedding model, max retries).

        Raises:
            QdrantKBError: If the configured Qdrant collection does not exist or is empty, if the GenAI SDK is unsupported, or if the embedding vector dimension does not match the configured Qdrant vector dimension.
        """
        self.logger: Logger = getLogger("zammad-ai.qdrant")

        self.collection_name: str = qdrant_settings.collection_name

        self.qdrant_settings: QdrantSettings = qdrant_settings
        # Create sync + async Qdrant client with appropriate configuration
        self.client = QdrantClient(
            url=qdrant_settings.url.encoded_string(),
            port=None,  # Port is included in the URL, so we set it to None
            timeout=qdrant_settings.timeout,
            api_key=qdrant_settings.api_key.get_secret_value() if qdrant_settings.api_key else None,
        )
        self.aclient = AsyncQdrantClient(
            url=qdrant_settings.url.encoded_string(),
            port=None,  # Port is included in the URL, so we set it to None
            timeout=qdrant_settings.timeout,
            api_key=qdrant_settings.api_key.get_secret_value() if qdrant_settings.api_key else None,
        )

        # Check if collection exists and if there is data in it, else raise an Error
        try:
            if not self.client.collection_exists(collection_name=qdrant_settings.collection_name):
                self.logger.error(f"Qdrant collection '{qdrant_settings.collection_name}' does not exist.")
                raise QdrantKBError(f"Qdrant collection '{qdrant_settings.collection_name}' does not exist.")

            collection_info: CollectionInfo = self.client.get_collection(
                collection_name=qdrant_settings.collection_name
            )
            if collection_info.points_count == 0:
                self.logger.warning(f"Qdrant collection '{qdrant_settings.collection_name}' exists but is empty.")
                raise QdrantKBError(f"Qdrant collection '{qdrant_settings.collection_name}' exists but is empty.")

        except ApiException as e:
            self.logger.error("Error checking Qdrant collection existence or retrieving collection info", exc_info=True)
            raise QdrantKBError("Failed to check Qdrant collection existence or retrieve collection info") from e

        # Create LangChain embedding model
        self.embeddings: Embeddings

        match genai_settings.sdk:
            case "openai":
                from langchain_openai import OpenAIEmbeddings

                self.embeddings = OpenAIEmbeddings(
                    model=genai_settings.embedding_model,
                    dimensions=qdrant_settings.vector_dimension,
                    max_retries=genai_settings.max_retries,
                )
            case _:
                self.logger.error(f"Unsupported GenAI SDK '{genai_settings.sdk}' for embeddings")
                raise QdrantKBError(f"Unsupported GenAI SDK '{genai_settings.sdk}' for embeddings")

        # Test embedding to ensure configuration is correct
        test_result: list[float] = self.embeddings.embed_query("This is a test string")
        if len(test_result) != qdrant_settings.vector_dimension:
            self.logger.error(
                f"Embedding dimension mismatch: expected {qdrant_settings.vector_dimension}, got {len(test_result)}. Check your GenAI embedding model configuration."
            )
            raise QdrantKBError(
                f"Embedding dimension mismatch: expected {qdrant_settings.vector_dimension}, got {len(test_result)}. Check your GenAI embedding model configuration."
            )

        # Create LangChain Qdrant vector store
        self.vectorstore = QdrantVectorStore(
            client=self.client,
            collection_name=qdrant_settings.collection_name,
            embedding=self.embeddings,
            vector_name=qdrant_settings.vector_name,
        )

        self.retriever: VectorStoreRetriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": qdrant_settings.retrieval_num_documents},
        )

    async def asearch_documents(
        self,
        query: str,
        k: int | None = None,
        offset: int = 0,
    ) -> list[tuple[Document, float]]:
        """Search for relevant documents in the Qdrant collection based on a query string.

        Args:
            query (str): The query string to search for relevant documents.
            k (int, optional): The number of top relevant documents to return.
            offset (int, optional): The number of top relevant documents to skip for pagination. Defaults to 0.

        Returns:
            list[tuple[Document, float]]: A list of tuples containing relevant documents and their corresponding relevance scores between 0 and 1.
        """
        if k is None:
            k = self.qdrant_settings.retrieval_num_documents
        return await self.vectorstore.asimilarity_search_with_relevance_scores(
            query=query,
            k=k,
            offset=offset,
        )

    def search_documents(
        self,
        query: str,
        k: int | None = None,
        offset: int = 0,
    ) -> list[tuple[Document, float]]:
        """Search for relevant documents in the Qdrant collection based on a query string.

        Args:
            query (str): The query string to search for relevant documents.
            k (int, optional): The number of top relevant documents to return.
            offset (int, optional): The number of top relevant documents to skip for pagination. Defaults to 0.

        Returns:
            list[tuple[Document, float]]: A list of tuples containing relevant documents and their corresponding relevance scores between 0 and 1.
        """
        if k is None:
            k = self.qdrant_settings.retrieval_num_documents
        return self.vectorstore.similarity_search_with_relevance_scores(
            query=query,
            k=k,
            offset=offset,
        )

    async def close(self) -> None:
        """Close the Qdrant client connections."""
        await self.aclient.close()
        self.client.close()
