"""Abstract base class for Zammad API clients."""

from abc import ABC, abstractmethod
from base64 import b64encode
from typing import Any

from httpx import AsyncClient, ConnectError, HTTPStatusError, ReadTimeout, TimeoutException
from stamina import retry_context

from app.models.zammad import ArticleAttachment, ZammadTicket
from app.settings.zammad import BaseZammadSettings
from app.utils.document_parser import DocumentParser
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
    async def fetch_ticket_attachment_data(
        self, ticket_id: int, article_id: int, attachment: ArticleAttachment
    ) -> str | None:
        """Fetch an attachment and return its content as text or base64.

        Args:
            ticket_id: ID of the ticket to which the attachment belongs.
            attachment: The attachment object containing ID and metadata.
            article_id: ID of the article to which the attachment belongs.

        Returns:
            str: Decoded text for text/* or JSON; base64 string for binary content.

        """
        ...

    def __init__(self, base_url: str, settings: BaseZammadSettings) -> None:
        """Initialize Zammad client with HTTP configuration.

        Args:
            base_url: Base URL for the Zammad instance.
            settings: ZammadSettings object containing configuration values.

        """
        self.client = AsyncClient(base_url=base_url, timeout=settings.timeout, proxy=settings.http_proxy_url)
        self.http_attempts = settings.max_retries + 1
        self.document_parser = DocumentParser(settings.document_parsing)

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
                        # Only retry HTTPStatusError for transient status codes and safe methods
                        if should_retry and (e.response.status_code == 429 or e.response.status_code >= 500):
                            # Convert to a retryable exception to trigger retry
                            raise TimeoutException("Transient HTTP error") from e
                        else:
                            # Don't retry for client errors (4xx except 429)
                            raise

                    content_type = response.headers.get("Content-Type", "").lower()
                    if content_type.startswith("application/json"):
                        return response.json()
                    elif content_type.startswith("text/"):
                        return response.text
                    else:
                        return b64encode(response.content).decode("ascii")
        except (HTTPStatusError, ConnectError, TimeoutException, ReadTimeout) as e:
            logger.error(f"Failed to execute {method} {url} after {self.http_attempts} attempts.", exc_info=True)
            raise ZammadConnectionError(f"Failed to execute {method} {url} after {self.http_attempts} attempts.") from e

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
        await self.document_parser.close()


class ZammadConnectionError(Exception):
    """Custom exception for Zammad connection errors.

    Raised when HTTP requests to Zammad fail due to network issues,
    authentication problems, or server errors.

    """

    pass
