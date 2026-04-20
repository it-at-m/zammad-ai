"""Zammad API client using token-based authentication."""

from base64 import b64decode
from logging import Logger
from typing import override

from feedparser import FeedParserDict
from feedparser import parse as feedparser
from pydantic import TypeAdapter, ValidationError

from app.errors import TicketNotFoundError, ZammadPayloadParseError
from app.models.zammad import (
    KnowledgeBaseAnswer,
    KnowledgeBaseAttachment,
    ZammadAnswer,
    ZammadAPISharedDraft,
    ZammadArticle,
    ZammadKnowledgebase,
    ZammadSharedDraftArticle,
    ZammadTagAdd,
    ZammadTicket,
)
from app.settings.zammad import ZammadAPISettings
from app.utils.logging import getLogger

from .base import BaseZammadClient

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
        self.client.headers.update({"Authorization": f"Bearer {settings.auth_token.get_secret_value()}"})

        self.kb_id = settings.knowledge_base_id
        self.rss_token = settings.rss_feed_token

    @override
    async def get_ticket(self, id: int) -> ZammadTicket:
        data = await self._request("GET", f"/api/v1/ticket_articles/by_ticket/{id}")
        try:
            articles = TypeAdapter(list[ZammadArticle]).validate_python(data)
        except ValidationError as e:
            raise ZammadPayloadParseError(f"Invalid ticket payload for ticket {id}") from e
        return ZammadTicket(id=id, articles=articles)

    @override
    async def post_answer(self, ticket_id: int, text: str, subject: str | None = None, internal: bool = False) -> None:
        payload = ZammadAnswer(ticket_id=ticket_id, body=text, internal=internal, subject=subject)
        await self._request("POST", "/api/v1/ticket_articles", json=payload.model_dump())
        logger.info(f"Posted answer to ticket {ticket_id}")

    @override
    async def post_shared_draft(self, ticket_id: int, text: str) -> None:
        payload = ZammadAPISharedDraft(new_article=ZammadSharedDraftArticle(body=text, ticket_id=ticket_id))
        await self._request("PUT", f"/api/v1/tickets/{ticket_id}/shared_draft", json=payload.model_dump(by_alias=True))
        logger.info(f"Posted shared draft to ticket {ticket_id}")

    @override
    async def add_tag_to_ticket(self, ticket_id: int, tag: str) -> None:
        payload = ZammadTagAdd(item=tag, o_id=ticket_id)
        await self._request("POST", "/api/v1/tags/add", json=payload.model_dump())
        logger.info(f"Added tag '{tag}' to ticket {ticket_id}")

    @override
    async def kb_info(self) -> ZammadKnowledgebase | None:
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot fetch KB info.")
            return None

        data = await self._request("GET", f"/api/v1/knowledge_bases/{self.kb_id}")
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
    async def parse_rss_feed(self) -> FeedParserDict | None:
        if not self.kb_id or not self.rss_token:
            logger.warning("Knowledge base ID or RSS feed token is not set. Cannot parse RSS feed.")
            return None

        url = f"/api/v1/knowledge_bases/{self.kb_id}/de-de/feed"
        text = await self._request("GET", url, params={"token": self.rss_token.get_secret_value()})

        try:
            decoded_text = b64decode(text).decode("utf-8")
            return feedparser(decoded_text)
        except Exception:
            return feedparser(text)

    @override
    async def get_kb_answer_by_id(self, answer_id: int) -> KnowledgeBaseAnswer | None:
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot fetch KB answer.")
            return None

        try:
            response = await self._request(
                "GET",
                f"/api/v1/knowledge_bases/{self.kb_id}/answers/{answer_id}?include_contents={answer_id}",
            )
        except TicketNotFoundError:
            logger.info(f"Knowledge base answer {answer_id} not found (404).")
            return None

        try:
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
        except (KeyError, TypeError, ValidationError) as e:
            raise ZammadPayloadParseError(f"Invalid knowledge base answer payload for id {answer_id}") from e

    @override
    async def fetch_kb_attachment_data(self, id: int) -> str | None:
        return await self._request("GET", f"/api/v1/attachments/{id}") if id else None

    @override
    async def fetch_ticket_attachment_data(self, ticket_id: int, attachment_id: int, article_id: int) -> str | None:
        return (
            await self._request("GET", f"/api/v1/ticket_attachment/{ticket_id}/{article_id}/{attachment_id}")
            if ticket_id and attachment_id and article_id
            else None
        )

    @override
    async def check_if_answer_exists(self, answer_id: int) -> bool:
        answer: KnowledgeBaseAnswer | None = await self.get_kb_answer_by_id(answer_id)
        return answer is not None
