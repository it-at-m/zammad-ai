import base64
from abc import ABC, abstractmethod
from typing import Any

import feedparser
from httpx import AsyncClient, ConnectError, HTTPStatusError, ReadTimeout, TimeoutException
from stamina import retry_context

from app.models.zammad import KnowledgeBaseAnswer, ZammadKnowledgebase, ZammadTicket
from app.utils.logging import getLogger

logger = getLogger("zammad-ai.base")


class BaseZammadClient(ABC):
    """Abstract base class for Zammad API clients."""

    @abstractmethod
    async def get_ticket(
        self,
        id: str,
    ) -> ZammadTicket:
        """
        Fetches ticket information for a given Zammad ticket ID.

        Parameters:
            id (str): Zammad ticket ID to retrieve.

        Returns:
            ZammadTicket: Ticket data corresponding to the provided ID.
        """
        ...

    @abstractmethod
    async def post_answer(
        self,
        ticket_id: str,
        text: str,
        subject: str | None = None,
        internal: bool = False,
    ) -> None:
        """
        Post an answer to the specified Zammad ticket.

        Parameters:
            ticket_id: ID of the ticket to update.
            text: Answer content to post.
            subject: Optional subject line for the answer.
            internal: If True, post as an internal note not visible to the customer.
        """
        ...

    @abstractmethod
    async def post_shared_draft(
        self,
        ticket_id: str,
        text: str,
    ) -> None:
        """
        Post a shared draft to the specified Zammad ticket.

        Parameters:
                ticket_id (str): ID of the ticket to post the shared draft to.
                text (str): Content of the shared draft.
        """
        ...

    @abstractmethod
    async def add_tag_to_ticket(
        self,
        ticket_id: str,
        tag: str,
    ) -> None:
        """
        Add the given tag to a Zammad ticket.
        
        Parameters:
            ticket_id (str): Identifier of the ticket to modify.
            tag (str): Tag string to add to the ticket.
        """
        ...

    @abstractmethod
    async def parse_rss_feed(self) -> feedparser.FeedParserDict | None:
        """
        Parse the knowledge base RSS feed and return the parsed feed.
        
        Returns:
            feedparser.FeedParserDict | None: Parsed feed object when successful, or `None` if the feed cannot be retrieved or parsed.
        """
        ...

    @abstractmethod
    async def show_kb(self) -> ZammadKnowledgebase | None:
        """
        Retrieve the knowledge base contents from Zammad.
        
        Returns:
            ZammadKnowledgebase | None: A `ZammadKnowledgebase` containing fetched knowledge base answers, or `None` if the knowledge base could not be retrieved or is unavailable.
        """
        ...

    @abstractmethod
    async def get_kb_answer_by_id(self, answer_id: str) -> KnowledgeBaseAnswer | None:
        """
        Retrieve a knowledge base answer by its ID.
        
        Parameters:
            answer_id (str): The knowledge base answer identifier.
        
        Returns:
            KnowledgeBaseAnswer | None: The answer if found, `None` if no answer exists with the given ID.
        """
        ...

    @abstractmethod
    async def fetch_kb_attachment_data(self, id: str) -> str | None:
        """
        Fetch a knowledge-base attachment by ID and return its content as text or base64.
        
        Parameters:
            id (str): Attachment identifier.
        
        Returns:
            str: Decoded text for `text/*` content types and JSON, or a base64-encoded string for binary content.
            None: If `id` is falsy or the attachment could not be retrieved.
        """
        ...

    @abstractmethod
    async def fetch_ticket_attachment_data(self, ticket_id: str, attachment_id: str, article_id: str) -> str | None:
        """
        Fetch an attachment and return its content as text or base64.

        Parameters:
            ticket_id (str): ID of the ticket to which the attachment belongs.
            attachment_id (str): ID of the attachment to fetch.
            article_id (str): ID of the article to which the attachment belongs.

        Returns:
            str: Decoded text for text/* or JSON; base64 string for binary content.
        """
        ...

    @abstractmethod
    async def check_if_answer_exists(self, answer_id: str) -> bool:
        """
        Determine whether a knowledge base answer with the given ID exists.
        
        Parameters:
            answer_id (str): Knowledge base answer identifier.
        
        Returns:
            bool: `True` if an answer with the given ID exists, `False` otherwise.
        """
        ...

    def __init__(self, base_url: str, timeout: int, max_retries: int, proxy_url: str | None = None) -> None:
        """
        Initialize the client with base URL, request timeout, proxy, and retry settings.
        
        Parameters:
            base_url (str): Base URL for Zammad API requests.
            timeout (int): Request timeout in seconds.
            max_retries (int): Maximum number of retry attempts for requests (client will attempt max_retries + 1 times).
            proxy_url (str | None): Optional proxy URL to route HTTP requests through.
        """
        self.client = AsyncClient(base_url=base_url, timeout=timeout, proxy=proxy_url)
        self.http_attempts = max_retries + 1

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """
        Perform an HTTP request and return the response body in an appropriate format.
        
        Parameters:
            method (str): HTTP method to use (e.g., "GET", "POST").
            url (str): Request URL or path relative to the client's base URL.
            **kwargs: Forwarded to the underlying HTTP client's request method.
        
        Returns:
            If the response Content-Type starts with "application/json", the parsed JSON object; if it starts with "text/", the response text; otherwise the response body encoded as an ASCII base64 string.
        
        Raises:
            ZammadConnectionError: If the request fails after the configured retry attempts for safe methods or on any allowed connection/timeout/http errors.
        """
        try:
            safe_methods = {"GET", "HEAD", "OPTIONS"}
            should_retry = method.upper() in safe_methods
            retry_on = (HTTPStatusError, ConnectError, TimeoutException, ReadTimeout) if should_retry else ()
            for attempt in retry_context(
                on=retry_on,
                attempts=self.http_attempts if should_retry else 1,
            ):
                with attempt:
                    response = await self.client.request(method, url, **kwargs)
                    response.raise_for_status()

                    content_type = response.headers.get("Content-Type", "").lower()
                    if content_type.startswith("application/json"):
                        return response.json()
                    elif content_type.startswith("text/"):
                        return response.text
                    else:
                        return base64.b64encode(response.content).decode("ascii")
        except (HTTPStatusError, ConnectError, TimeoutException, ReadTimeout) as e:
            logger.error(f"Failed to execute {method} {url} after {self.http_attempts} attempts.", exc_info=True)
            raise ZammadConnectionError(f"Failed to execute {method} {url} after {self.http_attempts} attempts.") from e

    async def cleanup(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()


class ZammadConnectionError(Exception):
    """Custom exception for Zammad connection errors."""

    pass
