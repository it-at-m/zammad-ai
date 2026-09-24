"""Zammad API client using token-based authentication."""

from base64 import b64decode
from binascii import Error as BinasciiError
from datetime import datetime, timedelta
from logging import Logger
from typing import Any, override

from pydantic import TypeAdapter, ValidationError

from app.errors import ZammadPayloadParseError
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


def _extract_group_name(data: dict[str, Any]) -> str | None:
    for key in ("group_name", "groupName", "group", "name"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    group = data.get("group")
    if isinstance(group, dict):
        for key in ("group_name", "groupName", "name"):
            value = group.get(key)
            if isinstance(value, str) and value:
                return value
    return None


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
        request_kwargs: dict[str, Any] = {}
        if self.settings.ai_ticket_group_name is not None:
            request_kwargs["params"] = {"include": "group"}

        ticket_data = await self._request("GET", f"/api/v1/tickets/{id}", **request_kwargs)
        if not isinstance(ticket_data, dict):
            raise ZammadPayloadParseError(f"Invalid ticket payload for ticket {id}")
        try:
            raw_articles = ticket_data.get("articles")
            if not isinstance(raw_articles, list):
                raw_articles = await self._request("GET", f"/api/v1/ticket_articles/by_ticket/{id}")
            articles: list[ZammadArticle] = TypeAdapter(list[ZammadArticle]).validate_python(raw_articles)
            raw_group = ticket_data.get("group_id")
            group_id: int | None
            if raw_group in (None, ""):
                group_id = None
            else:
                try:
                    group_id = int(raw_group)
                except (TypeError, ValueError) as e:
                    raise ZammadPayloadParseError(f"Invalid group_id value for ticket {id}") from e
        except ValidationError as e:
            raise ZammadPayloadParseError(f"Invalid ticket payload for ticket {id}") from e
        group_name = _extract_group_name(ticket_data)
        if group_name is None and self.settings.ai_ticket_group_name is not None and group_id is not None:
            try:
                group_data = await self._request("GET", f"/api/v1/groups/{group_id}")
            except Exception:
                group_data = None
            if isinstance(group_data, dict):
                group_name = _extract_group_name(group_data)
        return ZammadTicket(
            id=id,
            articles=articles,
            group_id=group_id,
            group_name=group_name,
            article_count=len(articles),
        )

    @override
    async def post_answer(self, ticket_id: int, text: str, subject: str | None = None, internal: bool = False) -> None:
        payload = ZammadAnswer(ticket_id=ticket_id, body=text, internal=internal, subject=subject)
        await self._request("POST", "/api/v1/ticket_articles", json=payload.model_dump())
        logger.info(f"Posted answer to ticket {ticket_id}")

    @override
    async def update_ticket_group(self, ticket_id: int, group_id: int) -> None:
        payload = {"group_id": group_id, "id": ticket_id}
        await self._request("PUT", f"/api/v1/tickets/{ticket_id}", json=payload)
        logger.info(f"Updated ticket {ticket_id} group to {group_id}")

    @override
    async def set_ticket_pending_close(self, ticket_id: int, days: int) -> None:
        pending_date = (datetime.now() + timedelta(days=days)).isoformat()
        payload = {"id": ticket_id, "state": "pending close", "pending_time": pending_date}
        await self._request("PUT", f"/api/v1/tickets/{ticket_id}", json=payload)
        logger.info(f"Updated ticket {ticket_id} to pending close after {days} days")

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
        if attachment.filename.split(".")[-1].lower() not in self.settings.document_parsing.document_types:
            logger.debug(
                f"Skipping attachment {attachment.id} for ticket {ticket_id}, article {article_id} due to unsupported document type."
            )
            return None

        data: Any | None = (
            await self._request("GET", f"/api/v1/ticket_attachment/{ticket_id}/{article_id}/{attachment.id}")
            if ticket_id is not None and attachment.id is not None and article_id is not None
            else None
        )
        if not data:
            return None

        if not self.settings.document_parsing.mode == "off":
            try:
                if isinstance(data, str):
                    try:
                        document_data = b64decode(data, validate=True)
                    except BinasciiError, ValueError:
                        document_data = data.encode("utf-8")
                else:
                    document_data = data
                return await self.document_parser.parse(document_data, attachment)
            except Exception:
                logger.error(
                    f"Error processing attachment {attachment.id} for ticket {ticket_id}, article {article_id}",
                    exc_info=True,
                )
        # If mode is off or any error occurs, return original data
        return data
