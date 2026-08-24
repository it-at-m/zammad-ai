"""Qdrant knowledge-base client and retrieval helpers."""

from logging import Logger
from uuid import NAMESPACE_DNS, UUID, uuid5

from langchain_classic.retrievers.multi_query import MultiQueryRetriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from pydantic import BaseModel, Field, NonNegativeInt, PositiveInt
from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http.exceptions import ApiException
from qdrant_client.http.models import CollectionInfo
from qdrant_client.models import FieldCondition, Filter, IsEmptyCondition, MatchValue, PayloadField

from app.errors import QdrantPermanentError, QdrantRetryableError
from app.settings import MultiQuerySettings, QdrantSettings
from app.settings.genai import GenAIProviderSettings
from app.utils.genai_provider import get_chat_model
from app.utils.logging import getLogger

from .multiquery_helper import MULTI_QUERY_PROMPT, _build_queries, _search_documents_across_queries

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

    documents_with_relevance_score: list[tuple[KBDocument | Document | LawDocument, float]] = Field(
        description="A list of tuples containing retrieved documents and their corresponding relevance scores between 0 and 1",
    )


class KBDocument(BaseModel):
    """A document retrieved from the knowledge-base."""

    title: str = Field(description="The title of the document")
    body: str = Field(description="The body content of the document")
    url: str = Field(description="The URL of the document")


class LawDocument(BaseModel):
    """A document retrieved from the knowledge-base that is specifically related to a law."""

    title: str = Field(description="The title of the document")
    body: str = Field(description="The body content of the document")
    url: str = Field(description="The URL of the document")
    document_type: str = Field(description="The type of the document, e.g., 'paragraph', 'annex', etc.")


class QdrantKBError(QdrantPermanentError):
    """Custom exception for Qdrant-related errors."""

    ...


class QdrantKBClient:
    """Wrapper around Qdrant client to handle vector storage and retrieval."""

    def __init__(self, qdrant_settings: QdrantSettings, genai_settings: GenAIProviderSettings) -> None:
        # Create logger for QdrantClient
        """Initialize the QdrantKBClient, configure Qdrant clients, embeddings, vector store, and retriever.

        Parameters:
            qdrant_settings (QdrantSettings): Configuration for Qdrant connection, collection, vector dimensions, vector name, timeout, and retrieval defaults.
            genai_settings (GenAIProviderSettings): Configuration for the embedding provider (SDK, embedding model, max retries).

        Raises:
            QdrantKBError: If the configured Qdrant collection does not exist or is empty, if the GenAI SDK is unsupported, or if the embedding vector dimension does not match the configured Qdrant vector dimension.
        """
        self.logger: Logger = getLogger("zammad-ai.qdrant")

        self.collection_name: str = qdrant_settings.collection_name

        self.qdrant_settings: QdrantSettings = qdrant_settings
        self.multi_query_settings: MultiQuerySettings = qdrant_settings.multi_query
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

        except ApiException as e:
            self.logger.error("Error checking Qdrant collection existence or retrieving collection info", exc_info=True)
            status = getattr(e, "status", None)
            if isinstance(status, int) and status >= 500:
                raise QdrantRetryableError(
                    "Failed to check Qdrant collection existence or retrieve collection info"
                ) from e
            raise QdrantKBError("Failed to check Qdrant collection existence or retrieve collection info") from e

        # Create LangChain embedding model
        self.embeddings: Embeddings

        match genai_settings.sdk:
            case "openai" | "anthropic":
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

        vector_name = qdrant_settings.vector_name
        # Short startup log showing which Qdrant vector name is being used.
        self.logger.info(f"Qdrant vector name: '{vector_name}'")

        # Determine retrieval mode (dense, sparse, hybrid) and optionally provide
        # a sparse embedding implementation required by SPARSE/HYBRID modes.
        requested_mode = getattr(self.qdrant_settings, "retrieval_mode", "dense")
        try:
            retrieval_mode = RetrievalMode.DENSE
            if isinstance(requested_mode, str):
                match requested_mode.lower():
                    case "dense":
                        retrieval_mode = RetrievalMode.DENSE
                    case "sparse":
                        retrieval_mode = RetrievalMode.SPARSE
                    case "hybrid":
                        retrieval_mode = RetrievalMode.HYBRID
                    case _:
                        self.logger.warning(
                            "Unknown Qdrant retrieval_mode '%s', defaulting to 'dense'",
                            requested_mode,
                        )
        except Exception:
            retrieval_mode = RetrievalMode.DENSE

        sparse_embedding = None
        if retrieval_mode in (RetrievalMode.SPARSE, RetrievalMode.HYBRID):
            try:
                from langchain_qdrant.fastembed_sparse import FastEmbedSparse

                # Provide a default sparse embedding implementation. If the
                # dependency isn't available we'll fall back to dense retrieval.
                sparse_embedding = FastEmbedSparse()
            except Exception:
                self.logger.warning(
                    "Requested Qdrant retrieval_mode '%s' but no sparse embedding is available. Falling back to 'dense'.",
                    requested_mode,
                    exc_info=True,
                )
                retrieval_mode = RetrievalMode.DENSE
                sparse_embedding = None

        # Create LangChain Qdrant vector store with configured retrieval mode.
        self.vectorstore = QdrantVectorStore(
            client=self.client,
            collection_name=qdrant_settings.collection_name,
            embedding=self.embeddings,
            vector_name=vector_name,
            retrieval_mode=retrieval_mode,
            sparse_embedding=sparse_embedding,
            sparse_vector_name=getattr(self.qdrant_settings, "sparse_vector_name", "langchain-sparse"),
        )

        # Use a supported search_type; 'similarity' works for dense and hybrid stores.
        self.retriever: VectorStoreRetriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": qdrant_settings.retrieval_num_documents},
        )

        self.multi_query_retriever: MultiQueryRetriever | None = None
        if self.multi_query_settings.enabled:
            query_llm = get_chat_model(genai_settings, "answer")
            generated_multi_query_retriever: MultiQueryRetriever = MultiQueryRetriever.from_llm(
                retriever=self.retriever,
                llm=query_llm,
                prompt=MULTI_QUERY_PROMPT,
                include_original=self.multi_query_settings.include_original,
            )
            setattr(generated_multi_query_retriever, "verbose", False)
            self.multi_query_retriever: MultiQueryRetriever = generated_multi_query_retriever

    async def asearch_documents(
        self,
        query: str,
        k: int | None = None,
        offset: int = 0,
        search_filter: Filter | None = None,
    ) -> list[tuple[Document, float]]:
        """Search for relevant documents in the Qdrant collection based on a query string.

        Args:
            query (str): The query string to search for relevant documents.
            k (int, optional): The number of top relevant documents to return.
            offset (int, optional): The number of top relevant documents to skip for pagination. Defaults to 0.
            search_filter (Filter, optional): Optional Qdrant metadata filter to scope retrieval.

        Returns:
            list[tuple[Document, float]]: A list of tuples containing relevant documents and their corresponding relevance scores between 0 and 1.
        """
        if k is None:
            k = self.qdrant_settings.retrieval_num_documents
        search_k = k

        # By default, restrict general knowledge-base searches to points that
        # are NOT law-indexed. Laws are stored in the same collection and are
        # identified by the presence of the metadata key `law_id`. When no
        # explicit search_filter is provided, add a filter that requires
        # metadata.law_id to be null (i.e., the key does not exist), so law
        # chunks are excluded from general KB searches and remain accessible
        # only via dedicated law tools.
        if search_filter is None:
            search_filter = Filter(must=[IsEmptyCondition(is_empty=PayloadField(key="metadata.law_id"))])

        multi_query_retriever = getattr(self, "multi_query_retriever", None)
        multi_query_settings = getattr(self, "multi_query_settings", None)
        if not isinstance(multi_query_settings, MultiQuerySettings):
            multi_query_settings = MultiQuerySettings()

        queries: list[str] = await _build_queries(query, multi_query_retriever, multi_query_settings)
        if len(queries) == 1:
            return await self.vectorstore.asimilarity_search_with_relevance_scores(
                query=query,
                k=search_k,
                offset=offset,
                filter=search_filter,
            )

        return await _search_documents_across_queries(
            vectorstore=self.vectorstore,
            retrieval_num_documents=self.qdrant_settings.retrieval_num_documents,
            queries=queries,
            k=search_k,
            offset=offset,
            search_filter=search_filter,
        )

    async def asearch_law_documents(
        self,
        law_id: str,
        query: str,
        k: int | None = None,
        offset: int = 0,
    ) -> list[tuple[Document, float]]:
        """Search indexed law chunks for one configured law."""
        law_filter = Filter(
            must=[
                FieldCondition(key="metadata.source", match=MatchValue(value="law")),
                FieldCondition(key="metadata.law_id", match=MatchValue(value=law_id)),
            ]
        )
        return await self.asearch_documents(
            query=query,
            k=k,
            offset=offset,
            search_filter=law_filter,
        )

    async def close(self) -> None:
        """Close the Qdrant client connections."""
        await self.aclient.close()
        self.client.close()
