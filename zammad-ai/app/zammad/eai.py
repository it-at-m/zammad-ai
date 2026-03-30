"""Zammad EAI client using OAuth 2.0 authentication."""

import asyncio
from base64 import b64decode
from datetime import datetime, timedelta
from logging import Logger
from typing import Any, override

from feedparser import FeedParserDict
from feedparser import parse as feedparser
from httpx import HTTPStatusError, RequestError
from pydantic import TypeAdapter

from app.models.zammad import (
    KnowledgeBaseAnswer,
    ZammadAnswer,
    ZammadArticle,
    ZammadEAISharedDraft,
    ZammadKnowledgebase,
    ZammadTicket,
)
from app.settings.zammad import ZammadEAISettings
from app.utils.logging import getLogger

from .base import BaseZammadClient, ZammadConnectionError

logger: Logger = getLogger("zammad-ai.zammad.eai")


class ZammadEAIClient(BaseZammadClient):
    """Zammad EAI client implementation for Zammad AI with OAuth 2.0 support."""

    def __init__(self, settings: ZammadEAISettings):
        """Initialize Zammad EAI client with OAuth 2.0 authentication.

        Args:
            settings: EAI-specific configuration including OAuth credentials

        """
        super().__init__(
            base_url=settings.eai_url.encoded_string(),
            timeout=settings.timeout,
            max_retries=settings.max_retries,
            proxy_url=settings.http_proxy_url,
        )

        self.settings = settings
        self.kb_id = settings.knowledge_base_id
        self._token = None
        self._token_expires = None
        self._auth_lock = asyncio.Lock()

    async def _ensure_auth(self) -> None:
        """Ensure OAuth token is valid, refreshing if needed.

        Uses double-checked locking to prevent OAuth token refresh stampedes
        in concurrent scenarios. Tokens are refreshed 5 minutes before expiry.
        """
        # Fast-path check without lock
        if self._token and self._token_expires and datetime.now() < self._token_expires - timedelta(minutes=5):
            return

        # Double-checked locking to prevent OAuth stampede
        async with self._auth_lock:
            # Re-check token validity inside the lock
            if self._token and self._token_expires and datetime.now() < self._token_expires - timedelta(minutes=5):
                return

            # Get new token
            token_data = {
                "grant_type": "client_credentials",
                "client_id": self.settings.oauth2_client_id,
                "client_secret": self.settings.oauth2_client_secret.get_secret_value(),
            }
            if self.settings.oauth2_scope:
                token_data["scope"] = self.settings.oauth2_scope

            try:
                response = await self.client.post(
                    str(self.settings.oauth2_token_url),
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
            except (HTTPStatusError, RequestError) as e:
                raise ZammadConnectionError(
                    f"Failed to obtain OAuth token from {self.settings.oauth2_token_url}"
                ) from e

            token_resp = response.json()
            self._token = token_resp["access_token"]
            expires_in = token_resp.get("expires_in", 3600)
            self._token_expires = datetime.now() + timedelta(seconds=expires_in)

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """Make authenticated request with OAuth bearer token."""
        await self._ensure_auth()

        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"
        kwargs["headers"] = headers

        return await super()._request(method, url, **kwargs)

    @override
    async def get_ticket(self, id: int) -> ZammadTicket:
        data = await self._request("GET", f"/tickets/byId/{id}")
        articles = TypeAdapter(list[ZammadArticle]).validate_python(data["articles"])
        return ZammadTicket(id=id, articles=articles)

    @override
    async def post_answer(self, ticket_id: int, text: str, subject: str | None = None, internal: bool = False) -> None:
        payload = ZammadAnswer(ticket_id=ticket_id, body=text, internal=internal, subject=subject)
        await self._request("POST", f"/tickets/{ticket_id}/articles", json=payload.model_dump())
        logger.info(f"Posted answer to ticket {ticket_id}")

    @override
    async def post_shared_draft(self, ticket_id: int, text: str) -> None:
        payload = ZammadEAISharedDraft(body=text)
        await self._request("PUT", f"/tickets/{ticket_id}/shared_draft", json=payload.model_dump())
        logger.info(f"Posted shared draft to ticket {ticket_id}")

    @override
    async def add_tag_to_ticket(self, ticket_id: int, tag: str) -> None:
        raise NotImplementedError("Adding tag is not implemented yet.")

    @override
    async def kb_info(self) -> ZammadKnowledgebase | None:
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot fetch KB info.")
            return None

        data = await self._request("GET", f"/knowledgeBases/{self.kb_id}")
        return TypeAdapter(ZammadKnowledgebase).validate_python(data) if data else None

    @override
    async def parse_rss_feed(self) -> FeedParserDict | None:
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot parse RSS feed.")
            return None

        response = await self._request("GET", f"/knowledgeBases/{self.kb_id}/rss")

        try:
            text = b64decode(response).decode("utf-8")
        except Exception:
            # If decoding fails, assume it's already plain text
            text = response

        return feedparser(text)

    @override
    async def get_kb_answer_by_id(self, answer_id: int) -> KnowledgeBaseAnswer | None:
        if not self.kb_id:
            logger.warning("Knowledge base ID is not set. Cannot fetch KB answer.")
            return None

        try:
            response = await self._request("GET", f"/knowledgeBases/{self.kb_id}/answer/{answer_id}")
        except ZammadConnectionError as e:
            cause: BaseException | None = e.__cause__
            if isinstance(cause, HTTPStatusError) and cause.response.status_code == 404:
                logger.info(f"Knowledge base answer {answer_id} not found (404).")
                return None
            # Auth failures, 5xx, timeouts — re-raise so callers and check_if_answer_exists
            # don't silently treat them as "answer deleted"
            raise

        return TypeAdapter(KnowledgeBaseAnswer).validate_python(response)

    @override
    async def fetch_kb_attachment_data(self, id: int) -> str | None:
        data = await self._request("GET", f"/attachments/{id}") if id else None
        if not (id and data):
            return None
        decoded = b64decode(data)
        try:
            return decoded.decode("utf-8")
        except UnicodeDecodeError:
            # Return raw base64 string for binary attachments
            return data

    @override
    async def fetch_ticket_attachment_data(self, ticket_id: int, attachment_id: int, article_id: int) -> str | None:
        data = (
            await self._request("GET", f"/attachments/{ticket_id}/{article_id}/{attachment_id}")
            if ticket_id and attachment_id and article_id
            else None
        )
        if not data:
            return None
        decoded = b64decode(data)
        try:
            return decoded.decode("utf-8")
        except UnicodeDecodeError:
            # Return raw base64 string for binary attachments
            return data

    @override
    async def check_if_answer_exists(self, answer_id: int) -> bool:
        answer: KnowledgeBaseAnswer | None = await self.get_kb_answer_by_id(answer_id)
        return answer is not None

    @override
    async def close(self) -> None:
        """Cleanup tokens and close client."""
        self._token = None
        self._token_expires = None
        await super().close()
