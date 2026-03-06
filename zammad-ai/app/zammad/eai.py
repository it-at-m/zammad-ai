import base64
from datetime import datetime, timedelta
from logging import Logger
from typing import Any, override

import feedparser
from pydantic import TypeAdapter

from app.core.settings.zammad import ZammadEAISettings
from app.models.zammad import KnowledgeBaseAnswer, ZammadAnswer, ZammadArticle, ZammadKnowledgebase, ZammadSharedDraftEAI, ZammadTicket
from app.utils.logging import getLogger

from .base import BaseZammadClient

logger: Logger = getLogger("zammad-ai.zammad.eai")


class ZammadEAIClient(BaseZammadClient):
    """Zammad EAI client implementation for Zammad AI with OAuth 2.0 support."""

    def __init__(self, settings: ZammadEAISettings):
        """
        Initialize the Zammad EAI client using the provided settings and configure internal HTTP and OAuth state.
        
        Configures the underlying HTTP client (base URL, timeout, retries, proxy) from the given settings, stores the settings and configured knowledge base ID, and initializes internal OAuth token state.
        
        Parameters:
            settings (ZammadEAISettings): EAI-specific configuration used to configure the HTTP client, OAuth credentials/URLs, and knowledge base identifier.
        """
        super().__init__(
            base_url=settings.eai_url.encoded_string(),
            timeout=settings.timeout,
            max_retries=settings.max_retries,
            proxy_url=settings.proxy_url,
        )

        self.settings = settings
        self.kb_id = settings.knowledge_base_id
        self._token = None
        self._token_expires = None

    async def _ensure_auth(self) -> None:
        """
        Ensure a valid OAuth 2.0 access token is available for requests.
        
        Refreshes the access token when none is present or when the current token is due to expire within five minutes, and stores the access token and its expiration time on the instance.
        """
        if self._token and self._token_expires and datetime.now() < self._token_expires - timedelta(minutes=5):
            return

        # Get new token
        token_data = {
            "grant_type": "client_credentials",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret.get_secret_value(),
        }
        if self.settings.scope:
            token_data["scope"] = self.settings.scope

        response = await self.client.post(
            str(self.settings.token_url), data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()

        token_resp = response.json()
        self._token = token_resp["access_token"]
        expires_in = token_resp.get("expires_in", 3600)
        self._token_expires = datetime.now() + timedelta(seconds=expires_in)

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """
        Ensure a valid OAuth token and perform an HTTP request with the Authorization header set.
        
        This method obtains or refreshes the client OAuth token if needed, injects an
        `Authorization: Bearer <token>` header (overwriting any existing Authorization
        header) into the request, and delegates the call to the superclass request
        implementation.
        
        Returns:
            The response value returned by the underlying request implementation.
        """
        await self._ensure_auth()

        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"
        kwargs["headers"] = headers

        return await super()._request(method, url, **kwargs)

    @override
    async def get_ticket(self, id: str) -> ZammadTicket:
        """
        Retrieve a ticket by its ID and return it with parsed articles.
        
        Queries the API for the ticket at /tickets/byId/{id} and validates the `articles` field into `ZammadArticle` instances.
        
        Returns:
            ZammadTicket: Ticket populated with the provided `id` and a list of parsed `ZammadArticle` objects.
        """
        data = await self._request("GET", f"/tickets/byId/{id}")
        articles = TypeAdapter(list[ZammadArticle]).validate_python(data["articles"])
        return ZammadTicket(id=id, articles=articles)

    @override
    async def post_answer(self, ticket_id: str, text: str, subject: str | None = None, internal: bool = False) -> None:
        """
        Post an article answer to a Zammad ticket.
        
        Parameters:
        	ticket_id (str): ID of the ticket to post the article to.
        	text (str): Body text of the article.
        	subject (str | None): Optional subject/title for the article.
        	internal (bool): If `True`, mark the article as internal (visible to agents only); otherwise visible to the customer.
        """
        payload = ZammadAnswer(ticket_id=ticket_id, body=text, internal=internal, subject=subject)
        await self._request("POST", f"/tickets/{ticket_id}/articles", json=payload.model_dump())
        logger.info(f"Posted answer to ticket {ticket_id}")

    @override
    async def post_shared_draft(self, ticket_id: str, text: str) -> None:
        """
        Post a shared draft message to a ticket's shared draft field.
        
        Parameters:
            ticket_id (str): ID of the ticket to update.
            text (str): Draft text to store as the ticket's shared draft.
        """
        payload = ZammadSharedDraftEAI(body=text)
        await self._request("PUT", f"/tickets/{ticket_id}/shared_draft", json=payload.model_dump())
        logger.info(f"Posted shared draft to ticket {ticket_id}")

    @override
    async def add_tag_to_ticket(self, ticket_id: str, tag: str) -> None:
        """
        Indicates that adding a tag to a ticket is not implemented.
        
        Raises:
            NotImplementedError: Always raised with the message "Adding tag is not implemented yet."
        """
        raise NotImplementedError("Adding tag is not implemented yet.")

    @override
    async def show_kb(self) -> ZammadKnowledgebase | None:
        """
        Retrieve the configured knowledge base from Zammad.
        
        Returns:
            ZammadKnowledgebase or `None` if no knowledge base ID is configured or the server returned no data.
        """
        if not self.kb_id:
            return None

        data = await self._request("GET", f"/knowledgeBases/{self.kb_id}")
        return TypeAdapter(ZammadKnowledgebase).validate_python(data) if data else None

    @override
    async def parse_rss_feed(self) -> feedparser.FeedParserDict | None:
        """
        Parse the RSS feed for the configured knowledge base and return it as a feedparser object.
        
        If no knowledge base ID is configured, returns None. Attempts to decode a Base64-encoded response to UTF-8; if decoding fails, treats the response as plain text before parsing.
        
        Returns:
            feed (feedparser.FeedParserDict | None): Parsed feed object, or `None` if no knowledge base ID is set.
        """
        if not self.kb_id:
            return None

        response = await self._request("GET", f"/knowledgeBases/{self.kb_id}/rss")

        try:
            # If it's Base64-encoded XML, decode it
            import base64

            text = base64.b64decode(response).decode("utf-8")
        except Exception:
            # If decoding fails, assume it's already plain text
            text = response

        return feedparser.parse(text)

    @override
    async def get_kb_answer_by_id(self, answer_id: str) -> KnowledgeBaseAnswer | None:
        """
        Retrieve a knowledge base answer by its identifier.
        
        Parameters:
            answer_id (str): Identifier of the knowledge base answer to fetch.
        
        Returns:
            KnowledgeBaseAnswer | None: The validated knowledge base answer if found; `None` if no knowledge base is configured, the answer is not found, or retrieval/validation fails.
        """
        if not self.kb_id:
            return None

        try:
            response = await self._request("GET", f"/knowledgeBases/{self.kb_id}/answer/{answer_id}")
            return TypeAdapter(KnowledgeBaseAnswer).validate_python(response)
        except Exception:
            logger.warning(f"Failed to get knowledge base answer {answer_id}", exc_info=True)
            return None

    @override
    async def fetch_kb_attachment_data(self, id: str) -> str | None:
        """
        Fetches a knowledge-base attachment by its identifier and returns its content decoded as UTF-8.
        
        Parameters:
            id (str): The attachment identifier to retrieve.
        
        Returns:
            str | None: The attachment content decoded from Base64 to a UTF-8 string, or `None` if `id` is falsy or no data was returned.
        """
        data = await self._request("GET", f"/attachments/{id}") if id else None
        return base64.b64decode(data).decode("utf-8") if id and data else None

    @override
    async def fetch_ticket_attachment_data(self, ticket_id: str, attachment_id: str, article_id: str) -> str | None:
        """
        Retrieve and decode a ticket attachment's Base64 content.
        
        Returns:
            str: The attachment content decoded as UTF-8, or `None` if the attachment is not found or any of the provided IDs is falsy.
        """
        data = (
            await self._request("GET", f"/attachments/{ticket_id}/{article_id}/{attachment_id}")
            if ticket_id and attachment_id and article_id
            else None
        )
        return base64.b64decode(data).decode("utf-8") if data else None

    @override
    async def check_if_answer_exists(self, answer_id: str) -> bool:
        """
        Check whether a knowledge base answer with the given identifier exists.
        
        Parameters:
            answer_id (str): Identifier of the knowledge base answer to look up.
        
        Returns:
            bool: `true` if the answer exists, `false` otherwise.
        """
        answer: KnowledgeBaseAnswer | None = await self.get_kb_answer_by_id(answer_id)
        return answer is not None

    @override
    async def cleanup(self) -> None:
        """Cleanup tokens and close client."""
        self._token = None
        self._token_expires = None
        await super().cleanup()
