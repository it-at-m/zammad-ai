"""Entry point for the Zammad AI index job."""

# ruff: noqa: E402 (no import at top level) suppressed on this file as we need to inject the truststore before importing the other modules

from dotenv import load_dotenv
from truststore import inject_into_ssl

inject_into_ssl()
load_dotenv()

from logging import Logger
from uuid import UUID

from qdrant_client.models import Record

from job.data.processing import add_keywords_to_changed_data, filter_for_changed_data, prepare_qdrant_data
from job.data.retrieval import get_answers_data, retrieve_answer_ids, retrieve_deleted_answer_ids
from job.law.ingest import ingest_law
from job.models.qdrant import QdrantDocumentItem
from job.models.zammad import KnowledgeBaseAnswer
from job.qdrant.qdrant import QdrantKBClient
from job.settings.settings import ZammadAIIndexSettings, get_settings
from job.settings.zammad import ZammadAPISettings, ZammadEAISettings
from job.utils.logging import getLogger
from job.zammad.api import ZammadAPIClient
from job.zammad.eai import ZammadEAIClient

settings: ZammadAIIndexSettings = get_settings()
logger: Logger = getLogger("zammad-ai-index")


def run_indexing(
    qdrant_client: QdrantKBClient,
    zammad_client: ZammadAPIClient | ZammadEAIClient,
    snapshot_already_created: bool = False,
) -> None:
    """Execute the complete indexing workflow.

    Performs a nine-step process:
    0. Retrieves answer IDs of filtered categories if category filtering is enabled
    1. Retrieves answer IDs for processing based on configured criteria
    2. Fetches detailed answer data for the retrieved answer IDs
    3. Gets all points from Qdrant to compare with new data
    4. Prepares and filters data for Qdrant, keeping only new or changed documents
    5. Checks for deleted documents in Zammad and retrieves their IDs
    6. Creates a snapshot in Qdrant before indexing to allow rollback if needed
    7. Adds new and changed documents to Qdrant in batches for optimal performance
    8. Deletes documents from Qdrant that correspond to deleted answer IDs in Zammad

    The method handles errors gracefully and ensures cleanup of resources.
    Process completion status is logged at info level.

    Raises:
        Exception: Critical errors during indexing are logged and re-raised.

    """
    logger.info("Indexing process started", extra={"stage": "indexing"})

    try:
        # Step 0: Retrieve answer IDs of filtered categories if category filtering is enabled
        answer_ids_in_category: list[int] = zammad_client.get_answer_ids_of_categories(settings.zammad.category_ids)

        # Step 1: Retrieve answer IDs for processing
        answer_ids: list[int] = retrieve_answer_ids(zammad_client, answer_ids_in_category)
        answers: dict[int, KnowledgeBaseAnswer] = {}
        if not answer_ids:
            logger.info("No answer IDs found", extra={"stage": "retrieve_answer_ids", "count": 0})
        else:
            logger.info("Answer IDs retrieved", extra={"stage": "retrieve_answer_ids", "count": len(answer_ids)})

            # Step 2: Fetch detailed answer data
            answers: dict[int, KnowledgeBaseAnswer] = get_answers_data(answer_ids, zammad_client)

            if not answers:
                logger.info("No answer data retrieved", extra={"stage": "fetch_answers", "count": 0})
            else:
                logger.info("Answer data fetched", extra={"stage": "fetch_answers", "count": len(answers)})

        # Step 3: Get all points from Qdrant
        all_points: list[Record] = qdrant_client.get_all_points()

        # Step 4: Prepare and filter data for Qdrant
        qdrant_items: list[QdrantDocumentItem] = _prepare_and_filter_data(answers, all_points, zammad_client)

        # Step 5: Check for deleted documents
        deleted_answer_ids: list[UUID] = retrieve_deleted_answer_ids(all_points, zammad_client, answer_ids_in_category)

        if not qdrant_items:
            logger.info("No new or changed documents to index", extra={"stage": "prepare_documents", "count": 0})
            if deleted_answer_ids:
                logger.info("Deleted answers detected", extra={"stage": "delete_documents", "count": len(deleted_answer_ids)})
            else:
                logger.info("No deleted answer IDs detected", extra={"stage": "delete_documents", "count": 0})
                return
        else:
            logger.info("Documents prepared for Qdrant", extra={"stage": "prepare_documents", "count": len(qdrant_items)})

        # Step 6: Create Qdrant snapshot if not already created by caller
        snapshot_success: bool = True
        if not snapshot_already_created:
            snapshot_success = qdrant_client.create_snapshot()

        if snapshot_success:
            logger.info("Qdrant snapshot ready", extra={"stage": "snapshot"})
        else:
            logger.warning("Failed to create Qdrant snapshot before indexing. Exiting.")
            return

        # Step 7: Add documents to Qdrant
        if qdrant_items:
            success: bool = add_documents_to_qdrant(qdrant_items, qdrant_client)

            if success:
                logger.info("Documents indexed into Qdrant", extra={"stage": "write_documents", "count": len(qdrant_items)})
            else:
                logger.error("Failed to index documents into Qdrant.")
                return

        # Step 8: Delete documents from Qdrant for deleted answer IDs
        if deleted_answer_ids:
            try:
                qdrant_client.delete_points_by_ids(deleted_answer_ids)
                logger.info("Deleted documents from Qdrant", extra={"stage": "delete_documents", "count": len(deleted_answer_ids)})
            except Exception:
                logger.error("Failed to delete points for deleted answer IDs: %s", deleted_answer_ids, exc_info=True)

        logger.info("Indexing process completed", extra={"stage": "finished"})

    except Exception:
        logger.error("Critical error during indexing process", exc_info=True)
        raise


def _prepare_and_filter_data(
    answers: dict[int, KnowledgeBaseAnswer], all_points: list[Record], zammad_client: ZammadAPIClient | ZammadEAIClient
) -> list[QdrantDocumentItem]:
    """Prepare data for Qdrant and filter for changed documents only.

    Transforms knowledge base answers into Qdrant document format with metadata,
    then filters to include only documents that have changed since last indexing
    to avoid unnecessary re-processing.

    Args:
        answers: Dictionary mapping answer IDs to KnowledgeBaseAnswer objects
        all_points: List of all points in the Qdrant collection
        zammad_client: Zammad API client instance

    Returns:
        List of QdrantDocumentItem objects ready for indexing, containing only
        new or changed documents based on content hash comparison.

    """
    # Prepare data for Qdrant indexing
    qdrant_data: list[QdrantDocumentItem] = prepare_qdrant_data(
        answers=answers,
        client=zammad_client,
    )

    # Filter to only include changed documents
    filtered_items: list[QdrantDocumentItem] = filter_for_changed_data(
        new_qdrant_data=qdrant_data,
        all_points=all_points,
    )
    add_keywords_to_changed_data(filtered_items)

    return filtered_items


def add_documents_to_qdrant(qdrant_items: list[QdrantDocumentItem], qdrant_client: QdrantKBClient) -> bool:
    """Add documents to Qdrant in batches for optimal performance.

    Args:
        qdrant_items: List of QdrantDocumentItem objects containing id, content, and metadata for indexing
        qdrant_client: Instance of QdrantKBClient for interacting with Qdrant


    Returns:
        True if all documents were successfully added, False otherwise

    """
    if not qdrant_items:
        logger.info("No documents to add to Qdrant.")
        return True

    batch_size: int = settings.index.batch_size

    total_batches: int = (len(qdrant_items) + batch_size - 1) // batch_size
    successful_batches: int = 0

    logger.info("Starting to add %d documents to Qdrant in %d batches.", len(qdrant_items), total_batches)

    for i in range(0, len(qdrant_items), batch_size):
        batch_number: int = i // batch_size + 1
        batch: list[QdrantDocumentItem] = qdrant_items[i : i + batch_size]

        try:
            logger.info("Processing batch %d/%d with %d documents", batch_number, total_batches, len(batch))

            qdrant_client.add_documents(batch)

            logger.debug("Successfully added batch %d/%d to Qdrant", batch_number, total_batches)
            successful_batches += 1
        except Exception:
            logger.error("Exception occurred while processing batch %d/%d", batch_number, total_batches, exc_info=True)

    logger.info("Successfully processed %d/%d batches.", successful_batches, total_batches)
    return successful_batches == total_batches


def cleanup(zammad_client, qdrant_client) -> None:
    """Clean up resources and close connections.

    Properly closes Zammad client and Qdrant client connections to prevent
    resource leaks. This method is called in the finally block of run_indexing
    to ensure cleanup occurs even if errors are encountered.
    """
    cleanup_errors: list[Exception] = []

    if zammad_client:
        try:
            zammad_client.close()
            logger.debug("Closed Zammad client connection")
        except Exception as e:
            logger.error("Failed to close Zammad client connection", exc_info=True)
            cleanup_errors.append(e)

    if qdrant_client:
        try:
            qdrant_client.close()
            logger.debug("Closed Qdrant client connection")
        except Exception as e:
            logger.error("Failed to close Qdrant client connection", exc_info=True)
            cleanup_errors.append(e)

    if cleanup_errors:
        logger.warning("Cleanup finished with %d error(s).", len(cleanup_errors))


def main() -> None:
    """Run the index job once using the configured Zammad and Qdrant clients."""
    try:
        # Initialize Zammad client based on configuration
        if isinstance(settings.zammad, ZammadAPISettings):
            zammad_client = ZammadAPIClient(settings.zammad)
            logger.info("Initialized Zammad API-Client")
        elif isinstance(settings.zammad, ZammadEAISettings):
            zammad_client = ZammadEAIClient(settings.zammad)
            logger.info("Initialized Zammad EAI-Client")
        else:
            raise ValueError(f"Unsupported Zammad client type: {settings.zammad.type}")

        # Initialize Qdrant client
        qdrant_client: QdrantKBClient = QdrantKBClient(
            settings,
        )
        logger.info("Initialized Qdrant client")

        # Optional: Ingest configured laws into the same collection before KB indexing
        # Create a single Qdrant snapshot before any writes (laws + KB) so we can
        # roll back in case of failure. This avoids creating one snapshot per
        # law which is unnecessary and can be slow.
        snapshot_created = False
        if settings.laws:
            logger.info("Creating Qdrant snapshot before law ingestion")
            snapshot_created = qdrant_client.create_snapshot()
            if not snapshot_created:
                logger.warning("Failed to create Qdrant snapshot before law ingestion. Exiting.")
                return

            logger.info("Starting law ingestion for %d configured law(s)", len(settings.laws))
            for law in settings.laws:
                ingest_law(law, qdrant_client)
            logger.info("Completed law ingestion stage")

        # Run the indexing process. If we already created a snapshot above we
        # tell run_indexing to skip creating another one.
        run_indexing(qdrant_client, zammad_client, snapshot_already_created=snapshot_created)
    except Exception:
        getLogger("zammad-ai-index").error("Application encountered a critical error", exc_info=True)
        raise
    finally:
        cleanup(zammad_client, qdrant_client)


if __name__ == "__main__":
    main()
