"""Abstract base class for Zammad API clients."""

from abc import ABC, abstractmethod
from base64 import b64encode
from typing import Any

from feedparser import FeedParserDict
from httpx import AsyncClient, ConnectError, HTTPStatusError, ReadTimeout, TimeoutException
from stamina import retry_context

from app.errors import (
    TicketNotFoundError,
    ZammadAuthError,
    ZammadPayloadParseError,
    ZammadPermanentError,
    ZammadRetryableError,
)
from app.models.zammad import KnowledgeBaseAnswer, ZammadKnowledgebase, ZammadTicket
from app.utils.logging import getLogger

logger = getLogger("zammad-ai.base")


class BaseZammadClient(ABC):
    """Abstract base class for Zammad API clients."""

    @abstractmethod
    async def get_ticket(
        self,
        id: int,
    ) -> ZammadTicket:
        """Fetch ticket information for a given Zammad ticket ID.

        Args:
            id: Zammad ticket ID to retrieve.

        Returns:
            ZammadTicket: Ticket data corresponding to the provided ID.

        """
        ...

    @abstractmethod
    async def post_answer(
        self,
        ticket_id: int,
        text: str,
        subject: str | None = None,
        internal: bool = False,
    ) -> None:
        """Post an answer to the specified Zammad ticket.

        Args:
            ticket_id: ID of the ticket to update.
            text: Answer content to post.
            subject: Optional subject line for the answer.
            internal: If True, post as an internal note not visible to the customer.

        """
        ...

    @abstractmethod
    async def post_shared_draft(
        self,
        ticket_id: int,
        text: str,
    ) -> None:
        """Post a shared draft to the specified Zammad ticket.

        Args:
                ticket_id: ID of the ticket to post the shared draft to.
                text: Content of the shared draft.

        """
        ...

    @abstractmethod
    async def add_tag_to_ticket(
        self,
        ticket_id: int,
        tag: str,
    ) -> None:
        """Add a tag to the specified Zammad ticket.

        Args:
            ticket_id: Zammad ticket identifier.
            tag: Tag text to add to the ticket.

        """
        ...

    @abstractmethod
    async def parse_rss_feed(self) -> FeedParserDict | None:
        """Parse RSS feed from the knowledge base.

        Returns:
            feedparser.FeedParserDict: Parsed feed object or None if parsing fails.

        """
        ...

    @abstractmethod
    async def kb_info(self) -> ZammadKnowledgebase | None:
        """Fetch knowledge base information.

        Returns:
            ZammadKnowledgebase | None: Knowledge base information or None if fetching fails.

        """
        ...

    @abstractmethod
    async def get_kb_answer_by_id(self, answer_id: int) -> KnowledgeBaseAnswer | None:
        """Fetch a knowledge base answer by its ID.

        Args:
            answer_id: The ID of the answer to fetch.

        Returns:
            KnowledgeBaseAnswer | None: Knowledge base answer data or None if not found.

        """
        ...

    @abstractmethod
    async def fetch_kb_attachment_data(self, id: int) -> str | None:
        """Fetch an attachment and return its content as text or base64.

        Args:
            id: ID of the attachment to fetch.

        Returns:
            str: Decoded text for text/* or JSON; base64 string for binary content.
            None: On error or if id is falsy.

        """
        ...

    @abstractmethod
    async def fetch_ticket_attachment_data(self, ticket_id: int, attachment_id: int, article_id: int) -> str | None:
        """Fetch an attachment and return its content as text or base64.

        Args:
            ticket_id: ID of the ticket to which the attachment belongs.
            attachment_id: ID of the attachment to fetch.
            article_id: ID of the article to which the attachment belongs.

        Returns:
            str: Decoded text for text/* or JSON; base64 string for binary content.

        """
        ...

    @abstractmethod
    async def check_if_answer_exists(self, answer_id: int) -> bool:
        """Check if a knowledge base answer still exists.

        Args:
            answer_id: The ID of the answer to check.

        Returns:
            bool: True if answer exists, False if deleted/not found.

        """
        ...

    def __init__(self, base_url: str, timeout: int, max_retries: int, proxy_url: str | None = None) -> None:
        """Initialize Zammad client with HTTP configuration.

        Args:
            base_url: Base URL for the Zammad instance
            timeout: HTTP timeout in seconds
            max_retries: Maximum number of retry attempts
            proxy_url: Optional HTTP proxy URL

        """
        self.client = AsyncClient(base_url=base_url, timeout=timeout, proxy=proxy_url)
        self.http_attempts = max_retries + 1

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """Make HTTP request and return JSON or text."""
        try:
            safe_methods = {"GET", "HEAD", "OPTIONS"}
            should_retry = method.upper() in safe_methods
            retry_on = (ConnectError, TimeoutException, ReadTimeout) if should_retry else ()
            for attempt in retry_context(
                on=retry_on,
                attempts=self.http_attempts if should_retry else 1,
            ):
                with attempt:
                    try:
                        response = await self.client.request(method, url, **kwargs)
                        response.raise_for_status()
                    except HTTPStatusError as e:
                        status_code = e.response.status_code
                        if should_retry and (status_code == 429 or status_code >= 500):
                            raise TimeoutException("Transient HTTP error") from e
                        if status_code in (401, 403):
                            raise ZammadAuthError(f"Zammad auth failed for {method} {url}") from e
                        if status_code == 404:
                            raise TicketNotFoundError(f"Zammad resource not found for {method} {url}") from e
                        raise ZammadPermanentError(f"Zammad request failed for {method} {url}") from e

                    content_type = response.headers.get("Content-Type", "").lower()
                    if content_type.startswith("application/json"):
                        try:
                            return response.json()
                        except ValueError as e:
                            raise ZammadPayloadParseError(f"Invalid JSON response for {method} {url}") from e
                    elif content_type.startswith("text/"):
                        return response.text
                    else:
                        return b64encode(response.content).decode("ascii")
        except (ConnectError, TimeoutException, ReadTimeout) as e:
            logger.error(f"Failed to execute {method} {url} after {self.http_attempts} attempts.", exc_info=True)
            raise ZammadRetryableError(
                f"Failed to execute {method} {url} after {self.http_attempts} attempts.",
            ) from e
        except (TicketNotFoundError, ZammadAuthError, ZammadPayloadParseError, ZammadPermanentError):
            logger.error(f"Zammad request failed for {method} {url}.", exc_info=True)
            raise

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()


class ZammadConnectionError(ZammadRetryableError):
    """Custom exception for Zammad connection errors.

    Raised when HTTP requests to Zammad fail due to network issues,
    authentication problems, or server errors.

    """
