"""Service for retrieving data from Zammad knowledge base."""

from datetime import datetime, timedelta, timezone
from logging import Logger
from typing import Any
from uuid import UUID

from feedparser import FeedParserDict
from qdrant_client.models import Record

from job.models.zammad import KnowledgeBaseAnswer, ZammadKnowledgebase
from job.settings.settings import ZammadAIIndexSettings, get_settings
from job.utils.logging import getLogger
from job.zammad.api import ZammadAPIClient
from job.zammad.eai import ZammadEAIClient

logger: Logger = getLogger("zammad-ai-index.data-retrieval")
settings: ZammadAIIndexSettings = get_settings()


def retrieve_answer_ids(client: ZammadAPIClient | ZammadEAIClient) -> list[int]:
    """Retrieve knowledge base answer IDs for indexing.

    Depending on application configuration, either performs full indexing (all answers)
    or incremental indexing based on RSS feed (recent updates only). The indexing
    mode and interval are controlled by the application settings.

    Returns:
        List of knowledge base answer IDs to be processed for indexing

    Note:
        Errors are handled gracefully - failures are logged and an empty list
        is returned rather than raising exceptions.

    """
    if settings.index.full_indexing:
        return _get_all_answer_ids(client)

    return _get_recent_answer_ids_from_rss(settings.index.interval, client)


def _get_all_answer_ids(client: ZammadAPIClient | ZammadEAIClient) -> list[int]:
    """Retrieve all knowledge base answer IDs.

    Fetches the complete list of answer IDs from the knowledge base
    for full indexing operations. Used when incremental indexing is disabled.

    Returns:
        List of all answer IDs in the knowledge base, or empty list if
        the knowledge base information cannot be retrieved.

    """
    logger.info("Performing full indexing.")

    knowledgebase: ZammadKnowledgebase | None = client.kb_info()
    if knowledgebase:
        logger.info("Found %d answers in the knowledge base.", len(knowledgebase.answerIds))
        return knowledgebase.answerIds

    logger.error("Failed to fetch knowledge base information.")
    return []


def _get_recent_answer_ids_from_rss(interval_days: int, client: ZammadAPIClient | ZammadEAIClient) -> list[int]:
    """Retrieve recent answer IDs from RSS feed.

    Parses the knowledge base RSS feed to identify answers that have been
    updated within the specified time interval. Used for incremental indexing
    to avoid processing unchanged content.

    Args:
        interval_days: Number of days to look back from current time
        client: Zammad API client instance

    Returns:
        List of answer IDs that have been updated within the interval,
        or empty list if RSS feed cannot be parsed or no recent updates found.

    """
    logger.info("Performing indexing based on RSS feed.")

    feed: FeedParserDict | None = client.parse_rss_feed()
    if not feed:
        logger.error("Failed to parse RSS feed.")
        return []

    ids: list[int] = []
    cutoff_date: datetime = datetime.now(timezone.utc) - timedelta(days=interval_days)

    for entry in getattr(feed, "entries", []):
        try:
            updated_str = entry.get("updated")
            if not updated_str:
                logger.debug("Entry %s has no 'updated' field, skipping.", entry.get("id", "unknown"))
                continue
            updated: datetime = datetime.fromisoformat(updated_str)
            # Ensure datetime is timezone-aware (UTC if naive)
            if updated.tzinfo is None:
                updated: datetime = updated.replace(tzinfo=timezone.utc)

            if updated <= cutoff_date:
                continue

            # Extract answer ID from RSS entry ID format
            answer_id: int | None = _get_answer_id_from_entry(entry)
            if answer_id:
                ids.append(answer_id)

        except (ValueError, TypeError):
            logger.warning("Could not parse entry %s", entry.get("id", "unknown"), exc_info=True)
            continue

    logger.info("Found %d recent answers from RSS feed.", len(ids))
    return ids


def _get_answer_id_from_entry(entry: FeedParserDict) -> int | None:
    """Extract answer ID from RSS entry ID format.

    Parses the RSS entry ID string to extract the numeric answer ID.
    The ID format follows a pattern where the answer ID is the second-to-last
    component when split by hyphens.

    Args:
        entry: RSS feed entry dictionary containing the 'id' field

    Returns:
        Extracted numeric answer ID, or None if the ID format is invalid
        or cannot be parsed as an integer.

    """
    id_parts: list[str] = entry.get("id", "").split("-")
    if len(id_parts) >= 2:
        try:
            return int(id_parts[-2])
        except ValueError:
            pass
    return None


def get_answers_data(
    answer_ids: list[int], client: ZammadAPIClient | ZammadEAIClient
) -> dict[int, KnowledgeBaseAnswer]:
    """Fetch knowledge base answer data for given answer IDs.

    Args:
        answer_ids: List of answer IDs to fetch
        client: Zammad API client instance

    Returns:
        Dictionary mapping answer ID to KnowledgeBaseAnswer data

    """
    answers: dict[int, KnowledgeBaseAnswer] = {}

    for answer_id in answer_ids:
        data: KnowledgeBaseAnswer | None = client.get_kb_answer_by_id(answer_id)
        if not data:
            logger.warning("Answer with ID %d not found.", answer_id)
            continue
        answers[answer_id] = data

    logger.info("Successfully fetched data for %d/%d answers.", len(answers), len(answer_ids))
    return answers


def fetch_attachments_for_answer(
    answer: KnowledgeBaseAnswer, client: ZammadAPIClient | ZammadEAIClient
) -> dict[int, tuple[str, str | None]]:
    """Fetch attachment data for a given knowledge base answer.

    Args:
        answer: KnowledgeBaseAnswer object containing attachment metadata
        client: Zammad API client instance

    Returns:
        Dictionary mapping attachment ID to tuple of (filename, content)
        Content is None for unsupported file types

    """
    attachment_data: dict[int, tuple[str, str | None]] = {}

    for attachment in answer.attachments:
        data: str | None = None

        if attachment.contentType.startswith("text/"):
            try:
                data: str | None = client.fetch_kb_attachment_data(attachment.id)
            except Exception:
                logger.error(
                    "Failed to fetch attachment %d for answer ID %d",
                    attachment.id,
                    answer.id,
                    exc_info=True,
                )
        else:
            logger.info(
                "Skipping non-text attachment %s (ID: %d) for answer ID %d due to unsupported content type: %s",
                attachment.filename,
                attachment.id,
                answer.id,
                attachment.contentType,
            )

        attachment_data[attachment.id] = (attachment.filename, data)

    return attachment_data


def retrieve_deleted_answer_ids(all_points: list[Record], client: ZammadAPIClient | ZammadEAIClient) -> list[UUID]:
    """Retrieve IDs of knowledge base answers deleted since the last indexing run.

    This method checks for answers that were previously indexed but have been
    removed from the knowledge base, allowing the indexing process to keep the
    search index in sync with the current state of the knowledge base.

    Returns:
        list[UUID]: Deleted answer IDs, or an empty list if none are detected
        or retrieval fails.
    """
    deleted_ids: list[UUID] = []
    try:
        for point in all_points:
            answer_id: int | None = None
            try:
                payload: dict[str, Any] | None = point.payload
                if not payload:
                    logger.warning("Point with ID %s has no payload, skipping deletion check.", point.id)
                    continue

                metadata = payload.get("metadata")
                if not metadata:
                    logger.warning("Point with ID %s has no metadata, skipping deletion check.", point.id)
                    continue

                answer_id = metadata.get("answer_id")
                if answer_id is not None:
                    answer_id = int(answer_id)
                    if not client.check_if_answer_exists(answer_id):
                        logger.debug(
                            "Answer ID %d no longer exists in knowledge base, marking for deletion.", answer_id
                        )
                        deleted_ids.append(UUID(str(point.id)))
            except Exception:
                logger.error(
                    "Failed to process point ID %s for deletion check (answer ID: %s).",
                    point.id,
                    answer_id,
                    exc_info=True,
                )
                continue

        logger.info("Retrieved %d deleted answer IDs.", len(deleted_ids))
    except Exception:
        logger.error("Failed to retrieve deleted answer IDs.", exc_info=True)

    return deleted_ids
