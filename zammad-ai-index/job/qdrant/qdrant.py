"""Qdrant access helpers used by the index job."""

from logging import Logger
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ApiException
from qdrant_client.http.models import CollectionInfo
from qdrant_client.http.models.models import Record
from qdrant_client.models import SnapshotDescription

from job.models.qdrant import QdrantDocumentItem
from job.settings.genai import GenAISettings
from job.settings.settings import QdrantSettings, ZammadAIIndexSettings
from job.utils.logging import getLogger

# Create a consistent namespace UUID for generating vector IDs based on content
ZAMMAD_AI_NAMESPACE: UUID = uuid5(
    namespace=NAMESPACE_DNS,
    name="zammad-ai.muenchen.de",
)


class QdrantKBError(Exception):
    """Custom exception for Qdrant-related errors."""

    ...


class QdrantKBClient:
    """Wrapper around Qdrant client to handle vector storage and retrieval."""

    def __init__(self, settings: ZammadAIIndexSettings) -> None:
        """Initialize the client, embeddings, and vector store for the index job."""
        self.logger: Logger = getLogger("zammad-ai-index.qdrant")

        self.collection_name: str = settings.qdrant.collection_name
        self.settings: ZammadAIIndexSettings = settings
        self.qdrant_settings: QdrantSettings = settings.qdrant
        self.genai_settings: GenAISettings = settings.genai
        # Create sync + async Qdrant client with appropriate configuration
        self.client = QdrantClient(
            url=self.qdrant_settings.url.encoded_string(),
            port=None,  # Port is included in the URL, so we set it to None
            timeout=self.qdrant_settings.timeout,
            api_key=self.qdrant_settings.api_key.get_secret_value() if self.qdrant_settings.api_key else None,
        )

        # Check if collection exists and if there is data in it, else raise an Error
        try:
            if not self.client.collection_exists(collection_name=self.qdrant_settings.collection_name):
                self.logger.error(f"Qdrant collection '{self.qdrant_settings.collection_name}' does not exist.")
                raise QdrantKBError(f"Qdrant collection '{self.qdrant_settings.collection_name}' does not exist.")

            collection_info: CollectionInfo = self.client.get_collection(
                collection_name=self.qdrant_settings.collection_name
            )
            if collection_info.points_count == 0:
                self.logger.warning(f"Qdrant collection '{self.qdrant_settings.collection_name}' exists but is empty.")

        except ApiException as e:
            self.logger.error("Error checking Qdrant collection existence or retrieving collection info", exc_info=True)
            raise QdrantKBError("Failed to check Qdrant collection existence or retrieve collection info") from e

        # Create LangChain embedding model
        self.embeddings: Embeddings

        match self.genai_settings.sdk:
            case "openai":
                from langchain_openai import OpenAIEmbeddings

                self.embeddings = OpenAIEmbeddings(
                    model=self.genai_settings.embedding_model,
                    dimensions=self.qdrant_settings.vector_dimension,
                    max_retries=self.genai_settings.max_retries,
                )
            case _:
                self.logger.error(f"Unsupported GenAI SDK '{self.genai_settings.sdk}' for embeddings")
                raise QdrantKBError(f"Unsupported GenAI SDK '{self.genai_settings.sdk}' for embeddings")

        # Test embedding to ensure configuration is correct
        test_result: list[float] = self.embeddings.embed_query("This is a test string")
        if len(test_result) != self.qdrant_settings.vector_dimension:
            self.logger.error(
                f"Embedding dimension mismatch: expected {self.qdrant_settings.vector_dimension}, got {len(test_result)}. Check your GenAI embedding model configuration."
            )
            raise QdrantKBError(
                f"Embedding dimension mismatch: expected {self.qdrant_settings.vector_dimension}, got {len(test_result)}. Check your GenAI embedding model configuration."
            )

        # Create LangChain Qdrant vector store
        self.vectorstore = QdrantVectorStore(
            client=self.client,
            collection_name=self.qdrant_settings.collection_name,
            embedding=self.embeddings,
            vector_name=self.qdrant_settings.vector_name,
        )

        self.retriever: VectorStoreRetriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": self.qdrant_settings.retrieval_num_documents},
        )

    def create_snapshot(self) -> bool:
        """Create a snapshot of the Qdrant collection for backup purposes.

        Returns:
            bool: True if snapshot creation was successful, False otherwise.
        """
        snapshot_description: SnapshotDescription | None = self.client.create_snapshot(
            collection_name=self.collection_name, wait=True
        )
        return snapshot_description is not None

    def add_documents(self, items: list[QdrantDocumentItem]) -> None:
        """Add multiple Qdrant document items to the collection.

        Args:
            items: List of QdrantDocumentItem objects containing vector id,
                page content and metadata for each document.

        Returns:
            None
        """
        if not items:
            self.logger.debug("No documents provided to add_documents")
            return

        documents_to_add: list[Document] = []
        ids_to_add: list[str] = []
        for item in items:
            metadata_item: dict[str, Any] = item.metadata.model_dump(mode="json")
            id_item: UUID = item.vector_id
            document = Document(page_content=item.page_content, metadata=metadata_item)
            documents_to_add.append(document)
            ids_to_add.append(str(id_item))
        self.vectorstore.add_documents(documents=documents_to_add, ids=ids_to_add)

    def get_documents_by_ids(self, ids: list[UUID]) -> dict[UUID, Document]:
        """Retrieve a document from the Qdrant collection by its unique identifier.

        Args:
            ids (list[UUID]): The unique identifiers of the documents to retrieve.

        Returns:
            dict[UUID, Document]: A dictionary mapping the provided UUIDs to their corresponding Document objects. If a document with a given UUID is not found, it will not be included in the returned dictionary.

        Raises:
            QdrantKBError: If there is an error during retrieval from Qdrant, a QdrantKBError will be raised with details about the failure.
        """
        try:
            results: list[Record] = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[str(id) for id in ids],
            )
            if results:
                documents: dict[UUID, Document] = {}
                for result in results:
                    if result.payload and isinstance(result.id, str):
                        self.logger.debug(
                            f"Retrieved document with ID {result.id} from Qdrant: {result.payload.get('metadata', {}).get('answer_title', 'No title in metadata')}"
                        )
                        documents[UUID(result.id)] = Document(
                            page_content=result.payload.get("page_content", ""),
                            metadata=result.payload.get("metadata", {}),
                        )
                return documents
            else:
                self.logger.info(f"No documents found in Qdrant with IDs {ids}")
                return {}
        except Exception as e:
            self.logger.error(f"Error retrieving documents with IDs {ids} from Qdrant", exc_info=True)
            raise QdrantKBError("Failed to retrieve documents from Qdrant") from e

    def close(self) -> None:
        """Close the Qdrant client connections."""
        self.client.close()

    def delete_points_by_ids(self, ids: list) -> None:
        """Delete documents from the Qdrant collection by their unique identifiers.

        Args:
            ids (list[UUID]): The unique identifiers of the documents to delete.

        Returns:
            None

        Raises:
            QdrantKBError: If there is an error during deletion from Qdrant, a QdrantKBError will be raised with details about the failure.
        """
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=ids,
            )
            self.logger.info(f"Deleted documents with IDs {ids} from Qdrant")
        except Exception as e:
            self.logger.error(f"Error deleting documents with IDs {ids} from Qdrant", exc_info=True)
            raise QdrantKBError("Failed to delete documents from Qdrant") from e

    def get_all_points(self) -> list[Record]:
        """Retrieve all points from the Qdrant collection.

        Returns:
            list[Record]: A list of Record objects representing all points in the Qdrant collection. Each Record includes the point's ID, payload, and vector (if available).

        Raises:
            QdrantKBError: If there is an error during retrieval from Qdrant, a QdrantKBError will be raised with details about the failure.
        """
        try:
            # Retrieve all document IDs from Qdrant and convert them to integers
            all_points: list[Record] = []
            next_offset = None

            while True:
                points, next_offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=500,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    break

                all_points.extend(points)

                if next_offset is None:
                    break

            return all_points
        except Exception as e:
            self.logger.error("Error retrieving all answer IDs from Qdrant", exc_info=True)
            raise QdrantKBError("Failed to retrieve all points from Qdrant") from e
