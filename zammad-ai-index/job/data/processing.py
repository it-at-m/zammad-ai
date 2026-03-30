"""Service for processing and transforming knowledge base data."""

from datetime import datetime, timezone
from logging import Logger
from uuid import UUID, uuid5

from qdrant_client.models import Record

from job.data.retrieval import fetch_attachments_for_answer
from job.models.qdrant import QdrantDocumentItem, QdrantVectorMetadata
from job.models.zammad import KnowledgeBaseAnswer
from job.qdrant.qdrant import ZAMMAD_AI_NAMESPACE
from job.settings.settings import ZammadAIIndexSettings, get_settings
from job.utils.hash import hash_content, normalize_content
from job.utils.logging import getLogger
from job.zammad.api import ZammadAPIClient
from job.zammad.eai import ZammadEAIClient

logger: Logger = getLogger("zammad-ai-index.data-processing")
settings: ZammadAIIndexSettings = get_settings()


def prepare_qdrant_data(
    answers: dict[int, KnowledgeBaseAnswer], client: ZammadAPIClient | ZammadEAIClient
) -> list[QdrantDocumentItem]:
    """Prepare data for Qdrant indexing based on knowledge base answers.

    Args:
        answers: Dictionary of answer ID to KnowledgeBaseAnswer objects
        client: Zammad API client instance

    Returns:
        List of QdrantDocumentItem objects containing id, content, and metadata for indexing

    """
    qdrant_data: list[QdrantDocumentItem] = []

    for answer_id, answer in answers.items():
        try:
            # Build the main page content
            page_content = _build_page_content(answer)

            # Fetch and append attachment content
            attachment_data: dict[int, tuple[str, str | None]] = fetch_attachments_for_answer(answer, client)
            page_content += _format_attachments_content(attachment_data)

            # Create metadata
            metadata: QdrantVectorMetadata = _create_vector_metadata(answer, page_content)
            vector_id: UUID = uuid5(ZAMMAD_AI_NAMESPACE, f"KB-{metadata.answer_kb_id}-Answer-{metadata.answer_id}")
            item = QdrantDocumentItem(
                vector_id=vector_id,
                page_content=page_content,
                metadata=metadata,
            )
            qdrant_data.append(item)
        except Exception:
            logger.error("Failed to process answer %d", answer_id, exc_info=True)
            continue

    logger.info("Successfully prepared %d items for Qdrant indexing.", len(qdrant_data))
    return qdrant_data


def _build_page_content(answer: KnowledgeBaseAnswer) -> str:
    """Build the main page content from answer data.

    Creates a formatted string containing the answer title, ID, update timestamp,
    and body content for indexing. This content serves as the primary searchable
    text for the vector database.

    Args:
        answer: KnowledgeBaseAnswer object containing the answer data

    Returns:
        Formatted string containing the answer's searchable content

    """
    return f"{answer.answerTitle} (ID: {answer.id}, Updated: {answer.updatedAt.strftime('%Y-%m-%d %H:%M:%S')}): \n\n{answer.answerBody}\n\n"


def _format_attachments_content(attachment_data: dict[int, tuple[str, str | None]]) -> str:
    """Format attachment data into content string.

    Processes attachment data and formats it for inclusion in the searchable
    content. Only text-based attachments with content are included.

    Args:
        attachment_data: Dictionary mapping attachment ID to tuple of (filename, content)
                        where content may be None for unsupported file types

    Returns:
        Formatted string containing all text attachment content, or empty string
        if no text attachments are available

    """
    content = ""
    for attachment_id, (filename, data) in attachment_data.items():
        if data:
            content += f"Attachment {filename} (ID: {attachment_id}): \n{data}\n\n"
    return content


def _create_vector_metadata(answer: KnowledgeBaseAnswer, page_content: str) -> QdrantVectorMetadata:
    """Create vector metadata from answer data.

    Builds comprehensive metadata for the vector document including answer details,
    timestamps, attachments, URL generation, and content hash for change detection.
    The vector ID is generated as a UUID5 based on the knowledge base ID and answer ID.

    Args:
        answer: KnowledgeBaseAnswer object containing the source data
        page_content: Processed content string for hash calculation

    Returns:
        QdrantVectorMetadata object with complete metadata for vector storage

    """
    answer_url = None
    if settings.zammad.base_url:
        answer_url = f"{settings.zammad.base_url}#knowledge_base/{settings.zammad.knowledge_base_id}/locale/de-de/answer/{answer.id}"

    return QdrantVectorMetadata(
        vector_updatedAt=datetime.now(timezone.utc),
        answer_id=answer.id,
        answer_kb_id=settings.zammad.knowledge_base_id,
        answer_title=answer.answerTitle,
        answer_body=answer.answerBody,
        answer_createdAt=answer.createdAt,
        answer_updatedAt=answer.updatedAt,
        answer_attachments=answer.attachments,
        answer_url=answer_url,
        pagecontent_hash=hash_content(normalize_content(page_content)),
    )


def filter_for_changed_data(
    new_qdrant_data: list[QdrantDocumentItem], all_points: list[Record]
) -> list[QdrantDocumentItem]:
    """Filter the provided Qdrant data to include only entries that have changed since the last indexing.

    Args:
        new_qdrant_data: List of QdrantDocumentItem objects containing id, content, and metadata for indexing
        all_points: List of all points in the Qdrant collection

    Returns:
        Filtered list of QdrantDocumentItem objects containing only changed documents

    """
    if not new_qdrant_data:
        logger.info("No data provided for filtering.")
        return []

    # Get vector IDs for batch lookup
    vector_ids: set[UUID] = {item.vector_id for item in new_qdrant_data}

    # Get all existing documents in one batch call for efficiency
    qdrant_documents: dict[UUID, Record] = {}
    for point in all_points:
        try:
            point_id = UUID(str(point.id))
        except (TypeError, ValueError):
            logger.warning(
                "Skipping Qdrant point with non-UUID id %s during change detection.",
                point.id,
                exc_info=True,
            )
            continue
        if point_id in vector_ids:
            qdrant_documents[point_id] = point

    if not qdrant_documents:
        logger.info("No existing documents found in Qdrant, including all %d items for indexing.", len(new_qdrant_data))
        return new_qdrant_data

    filtered_data: list[QdrantDocumentItem] = []

    for item in new_qdrant_data:
        current_document: Record | None = qdrant_documents.get(item.vector_id)

        if not current_document:
            # No existing document means it's new and should be included
            logger.debug("No existing document found for answer ID %d, including in indexing.", item.metadata.answer_id)
            filtered_data.append(item)
        else:
            try:
                payload_metadata = current_document.payload.get("metadata", {}) if current_document.payload else {}
                current_metadata: QdrantVectorMetadata | None = (
                    QdrantVectorMetadata.model_validate(payload_metadata) if payload_metadata else None
                )
            except Exception:
                logger.warning(
                    "Failed to validate metadata for document %s, treating as new.", item.vector_id, exc_info=True
                )
                filtered_data.append(item)
                continue

            current_hash: str | None = current_metadata.pagecontent_hash if current_metadata else None
            new_hash: str | None = item.metadata.pagecontent_hash
            if current_hash != new_hash:
                # Content has changed, include for re-indexing
                logger.debug(
                    "Content changes detected for answer ID %d, including in re-indexing.", item.metadata.answer_id
                )
                filtered_data.append(item)
            else:
                # No changes detected, skip re-indexing
                logger.debug(
                    "No content changes detected for answer ID %d, skipping re-indexing.", item.metadata.answer_id
                )

    logger.info(
        "Filtered data to %d/%d items with detected changes for indexing.", len(filtered_data), len(new_qdrant_data)
    )
    return filtered_data
