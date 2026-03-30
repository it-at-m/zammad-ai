"""Abstract base class for Zammad API clients."""

from abc import ABC, abstractmethod
from base64 import b64encode
from typing import Any

from feedparser import FeedParserDict
from httpx import Client, ConnectError, HTTPStatusError, ReadTimeout, TimeoutException
from stamina import retry_context

from job.models.zammad import KnowledgeBaseAnswer, ZammadKnowledgebase
from job.utils.logging import getLogger

logger = getLogger("zammad-ai.base")


class BaseZammadClient(ABC):
    """Abstract base class for Zammad API clients."""

    @abstractmethod
    def parse_rss_feed(self) -> FeedParserDict | None:
        """Parse RSS feed from the knowledge base.

        Returns:
            feedparser.FeedParserDict: Parsed feed object or None if parsing fails.

        """
        ...

    @abstractmethod
    def kb_info(self) -> ZammadKnowledgebase | None:
        """Fetch knowledge base information.

        Returns:
            ZammadKnowledgebase | None: Knowledge base information or None if fetching fails.

        """
        ...

    @abstractmethod
    def get_kb_answer_by_id(self, answer_id: int) -> KnowledgeBaseAnswer | None:
        """Fetch a knowledge base answer by its ID.

        Args:
            answer_id: The ID of the answer to fetch.

        Returns:
            KnowledgeBaseAnswer | None: Knowledge base answer data or None if not found.

        """
        ...

    @abstractmethod
    def fetch_kb_attachment_data(self, id: int) -> str | None:
        """Fetch an attachment and return its content as text or base64.

        Args:
            id: ID of the attachment to fetch.

        Returns:
            str: Decoded text for text/* or JSON; base64 string for binary content.
            None: On error or if id is falsy.

        """
        ...

    @abstractmethod
    def check_if_answer_exists(self, answer_id: int) -> bool:
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
        self.client = Client(base_url=base_url, timeout=timeout, proxy=proxy_url)
        self.http_attempts = max_retries + 1

    def _request(self, method: str, url: str, *, parse_json: bool = True, **kwargs) -> Any:
        """Make HTTP request and return JSON, text, or base64.

        Args:
            method: HTTP method.
            url: Relative request URL.
            parse_json: Parse JSON responses into Python objects.
            **kwargs: Additional request arguments forwarded to httpx.

        Returns:
            Any: Parsed JSON object, response text, or base64-encoded bytes.

        """
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
                        response = self.client.request(method, url, **kwargs)
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
                        if parse_json:
                            return response.json()
                        return response.text
                    elif content_type.startswith("text/"):
                        return response.text
                    else:
                        return b64encode(response.content).decode("ascii")
        except (HTTPStatusError, ConnectError, TimeoutException, ReadTimeout) as e:
            logger.error(f"Failed to execute {method} {url} after {self.http_attempts} attempts.", exc_info=True)
            raise ZammadConnectionError(f"Failed to execute {method} {url} after {self.http_attempts} attempts.") from e

    def close(self) -> None:
        """Close HTTP client."""
        self.client.close()


class ZammadConnectionError(Exception):
    """Custom exception for Zammad connection errors.

    Raised when HTTP requests to Zammad fail due to network issues,
    authentication problems, or server errors.

    """

    pass
