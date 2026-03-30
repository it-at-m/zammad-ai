"""Zammad API client using token-based authentication."""

from base64 import b64decode
from logging import Logger
from typing import override

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

logger: Logger = getLogger("zammad-ai.zammad.api")


class ZammadAPIClient(BaseZammadClient):
    """Client for interacting with Zammad API to fetch and update ticket information."""

    def __init__(self, settings: ZammadAPISettings):
        """Initialize Zammad API client with token-based authentication.

        Args:
            settings: API-specific configuration including auth token

        """
        super().__init__(
            base_url=settings.base_url.encoded_string(),
            timeout=settings.timeout,
            max_retries=settings.max_retries,
            proxy_url=settings.http_proxy_url,
        )

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
    def fetch_kb_attachment_data(self, id: int) -> str | None:
        return self._request("GET", f"/api/v1/attachments/{id}", parse_json=False) if id else None

    @override
    def check_if_answer_exists(self, answer_id: int) -> bool:
        answer: KnowledgeBaseAnswer | None = self.get_kb_answer_by_id(answer_id)
        return answer is not None
