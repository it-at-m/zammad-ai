"""Abstract base class for Zammad API clients."""

from abc import ABC, abstractmethod
from base64 import b64encode
from typing import Any

from httpx import AsyncClient, ConnectError, HTTPStatusError, ReadTimeout, TimeoutException
from stamina import retry_context

from app.errors import (
    TicketNotFoundError,
    ZammadAuthError,
    ZammadPayloadParseError,
    ZammadPermanentError,
    ZammadRetryableError,
)
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
    async def update_ticket_group(
        self,
        ticket_id: int,
        group_id: int,
    ) -> None:
        """Update the group assignment for a specified Zammad ticket.

        Args:
            ticket_id: ID of the ticket to update.
            group_id: ID of the new group to assign to the ticket.
        """
        ...

    @abstractmethod
    async def set_ticket_pending_close(self, ticket_id: int, days: int) -> None:
        """Update the ticket state to "pending close".

        Args:
            ticket_id: ID of the ticket to update.
            days: Number of days after which the ticket should be marked as pending close.
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
                        status_code = e.response.status_code
                        if status_code == 429 or status_code >= 500:
                            if should_retry:
                                raise TimeoutException("Transient HTTP error") from e
                            raise ZammadRetryableError(f"Transient Zammad HTTP error for {method} {url}") from e
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
        except ZammadRetryableError:
            logger.error(f"Zammad request failed for {method} {url}.", exc_info=True)
            raise
        except TicketNotFoundError, ZammadAuthError, ZammadPayloadParseError, ZammadPermanentError:
            logger.error(f"Zammad request failed for {method} {url}.", exc_info=True)
            raise

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
        await self.document_parser.close()


class ZammadConnectionError(ZammadRetryableError):
    """Custom exception for Zammad connection errors.

    Raised when HTTP requests to Zammad fail due to network issues,
    authentication problems, or server errors.

    """
