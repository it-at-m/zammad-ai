"""Zammad API client using token-based authentication."""

from base64 import b64decode
from logging import Logger
from typing import Any, override

from feedparser import FeedParserDict
from feedparser import parse as feedparser
from httpx import HTTPStatusError

from job.models.zammad import (
    KnowledgeBaseAnswer,
    KnowledgeBaseAttachment,
    ZammadKnowledgebase,
)
from job.settings.zammad import ZammadAPISettings
from job.utils.logging import getLogger

from .base import BaseZammadClient, ZammadConnectionError

logger: Logger = getLogger("zammad-ai-index.zammad.api")


class ZammadAPIClient(BaseZammadClient):
    """Client for interacting with Zammad API to fetch and update ticket information."""

    def __init__(self, settings: ZammadAPISettings):
        """Initialize Zammad API client with token-based authentication.

        Args:
            settings: API-specific configuration including auth token

        """
        super().__init__(
            base_url=settings.base_url.encoded_string(),
            settings=settings,
        )
        self.settings: ZammadAPISettings = settings
        # Set auth header
        self.client.headers.update({"Authorization": f"Token token={settings.auth_token.get_secret_value()}"})

        self.kb_id = settings.knowledge_base_id
        self.rss_token = settings.rss_feed_token
        self.rss_feed_locale = settings.rss_feed_locale

    @override
    def kb_info(self) -> ZammadKnowledgebase | None:
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot fetch KB info.")
            return None

        data = self._request("GET", f"/api/v1/knowledge_bases/{self.kb_id}")
        return (
            ZammadKnowledgebase(
                id=data["id"],
                active=data["active"],
                createdAt=data["created_at"],
                updatedAt=data["updated_at"],
                categoryIds=data.get("category_ids", []),
                answerIds=data.get("answer_ids", []),
            )
            if data
            else None
        )

    @override
    def get_answer_ids_of_categories(self, category_ids: list[int]) -> list[int]:
        if not category_ids:
            return []
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot fetch answer IDs.")
            return []
        visited_categories: set[int] = set()
        answer_ids: set[int] = set()
        stack: list[int] = list(category_ids)
        while stack:
            category_id: int = stack.pop()
            if category_id in visited_categories:
                continue
            visited_categories.add(category_id)
            data = self._request("GET", f"/api/v1/knowledge_bases/{self.kb_id}/categories/{category_id}")
            if not data:
                continue
            stack.extend(data.get("child_ids", []))
            answer_ids.update(data["answer_ids"])
        return list(answer_ids)

    @override
    def parse_rss_feed(self) -> FeedParserDict | None:
        if not self.kb_id or not self.rss_token:
            logger.warning("Knowledge base ID or RSS feed token is not set. Cannot parse RSS feed.")
            return None

        url = f"/api/v1/knowledge_bases/{self.kb_id}/{self.rss_feed_locale}/feed"
        text = self._request("GET", url, params={"token": self.rss_token.get_secret_value()})

        try:
            decoded_text = b64decode(text).decode("utf-8")
            return feedparser(decoded_text)
        except Exception:
            return feedparser(text)

    @override
    def get_kb_answer_by_id(self, answer_id: int) -> KnowledgeBaseAnswer | None:
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot fetch KB answer.")
            return None

        try:
            response = self._request(
                "GET",
                f"/api/v1/knowledge_bases/{self.kb_id}/answers/{answer_id}?include_contents={answer_id}",
            )
        except ZammadConnectionError as e:
            cause: BaseException | None = e.__cause__
            if isinstance(cause, HTTPStatusError) and cause.response.status_code == 404:
                logger.info(f"Knowledge base answer {answer_id} not found (404).")
                return None
            # Auth failures, 5xx, timeouts — re-raise so callers and check_if_answer_exists
            # don't silently treat them as "answer deleted"
            raise

        return KnowledgeBaseAnswer(
            id=response["id"],
            answerTitle=response["assets"]["KnowledgeBaseAnswerTranslation"][str(answer_id)]["title"],
            answerBody=response["assets"]["KnowledgeBaseAnswerTranslationContent"][str(answer_id)]["body"],
            attachments=[
                KnowledgeBaseAttachment(
                    id=attachment["id"],
                    filename=attachment["filename"],
                    contentType=attachment["preferences"]["Content-Type"],
                )
                for attachment in response["assets"]["KnowledgeBaseAnswer"][str(answer_id)]["attachments"]
            ],
            createdAt=response["assets"]["KnowledgeBaseAnswer"][str(answer_id)]["created_at"],
            updatedAt=response["assets"]["KnowledgeBaseAnswer"][str(answer_id)]["updated_at"],
        )

    @override
    def fetch_kb_attachment_data(self, attachment: KnowledgeBaseAttachment) -> str | None:
        data: Any | None = (
            self._request("GET", f"/api/v1/attachments/{attachment.id}", parse_json=False)
            if attachment.id is not None
            else None
        )
        if attachment.filename.split(".")[-1].lower() not in self.settings.document_parsing.document_types:
            logger.debug(f"Skipping attachment {attachment.id} due to unsupported document type.")
            return None
        if data is None:
            return None
        content_type = attachment.contentType.split(";", 1)[0].lower()
        if not self.document_parser.mode == "off":
            try:
                if isinstance(data, str):
                    if content_type.startswith("text/") or content_type == "application/json":
                        document_data = data.encode("utf-8")
                    else:
                        document_data = b64decode(data)
                else:
                    document_data = data
                return self.document_parser.parse(document_data, attachment)
            except Exception:
                logger.error(
                    f"Error processing attachment {attachment.id} for knowledge base answer",
                    exc_info=True,
                )
        # If mode is off or any error occurs, return original data for text/* or JSON; otherwise None
        if content_type.startswith("text/") or content_type == "application/json":
            return data
        else:
            logger.warning(
                "Attachment %d has unsupported content type '%s'. Skipping content retrieval.",
                attachment.id,
                attachment.contentType,
            )
            return None

    @override
    def check_if_answer_exists(self, answer_id: int) -> bool:
        answer: KnowledgeBaseAnswer | None = self.get_kb_answer_by_id(answer_id)
        return answer is not None
