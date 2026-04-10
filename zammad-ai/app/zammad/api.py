"""Zammad API client using token-based authentication."""

from logging import Logger
from typing import Any, override

from pydantic import TypeAdapter

from app.models.zammad import (
    ArticleAttachment,
    ZammadAnswer,
    ZammadAPISharedDraft,
    ZammadArticle,
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
            settings=settings,
        )
        self.settings: ZammadAPISettings = settings
        # Set auth header
        self.client.headers.update({"Authorization": f"Bearer {settings.auth_token.get_secret_value()}"})

        self.kb_id = settings.knowledge_base_id
        self.rss_token = settings.rss_feed_token

    @override
    async def get_ticket(self, id: int) -> ZammadTicket:
        data = await self._request("GET", f"/api/v1/ticket_articles/by_ticket/{id}")
        articles = TypeAdapter(list[ZammadArticle]).validate_python(data)
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
    async def fetch_ticket_attachment_data(
        self,
        ticket_id: int,
        article_id: int,
        attachment: ArticleAttachment,
    ) -> str | None:
        data: Any | None = (
            await self._request("GET", f"/api/v1/ticket_attachment/{ticket_id}/{article_id}/{attachment.id}")
            if ticket_id is not None and attachment.id is not None and article_id is not None
            else None
        )
        if not data:
            return None
        try:
            document_data: Any = data.encode("utf-8") if isinstance(data, str) else data
            if self.settings.document_parsing.mode == "local":
                return await self.document_parser.parse_local(document_data)
            if self.settings.document_parsing.mode == "remote":
                return await self.document_parser.parse_remote(
                    data=document_data,
                    attachment=attachment,
                )
        except Exception:
            logger.error(
                f"Error processing attachment {attachment.id} for ticket {ticket_id}, article {article_id}",
                exc_info=True,
            )
        # If mode is off or any error occurs, return original data
        return data
