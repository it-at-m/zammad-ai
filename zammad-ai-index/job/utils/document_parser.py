"""Helpers for parsing attachment documents through Kreuzberg."""

from logging import Logger
from typing import Any, Literal

from httpx import Client, Response
from langchain_core.documents.base import Document

from job.models.zammad import KnowledgeBaseAttachment
from job.settings.zammad import DocumentParsingSettings

from .logging import getLogger

logger: Logger = getLogger("zammad-ai-index.utils.parse_document")
DEFAULT_MIME_TYPE = "application/octet-stream"


class DocumentParser:
    """Utility class for parsing attachment documents through Kreuzberg."""

    def __init__(self, settings: DocumentParsingSettings):
        """Initialize the DocumentParser with the given settings."""
        self.mode: Literal["off", "local", "remote"] = settings.mode
        if self.mode == "local":
            try:
                import langchain_kreuzberg  # noqa: F401
            except ImportError:
                logger.error("langchain_kreuzberg is not installed. Local Kreuzberg parsing will be unavailable.")
                self.mode = "off"

        elif self.mode == "remote":
            self.client = Client(timeout=120, proxy=settings.http_proxy_url, base_url=str(settings.url))

    def parse_local(self, data: Any) -> str:
        """Process attachment content using local Kreuzberg.

        Args:
            data: Attachment payload from Zammad as bytes or a file-like object.

        Returns:
            The extracted document text.
        """
        from langchain_kreuzberg import KreuzbergLoader

        document_bytes: bytes = self._coerce_document_bytes(data)
        loader = KreuzbergLoader(
            data=document_bytes,
            mime_type=DEFAULT_MIME_TYPE,
        )
        docs: list[Document] = loader.load()
        if not isinstance(docs, list) or not docs:
            raise ValueError("Kreuzberg did not return any documents for the attachment.")
        logger.info("Successfully processed document with local Kreuzberg.")
        return docs[0].page_content

    def _coerce_document_bytes(self, data: Any) -> bytes:
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        if isinstance(data, memoryview):
            return data.tobytes()
        if hasattr(data, "read"):
            return self._coerce_document_bytes(data.read())
        raise TypeError(f"Unsupported document payload type: {type(data).__name__}")

    def parse_remote(self, data: Any, attachment: KnowledgeBaseAttachment) -> str:
        """Send attachment content to a remote Kreuzberg API server.

        Args:
            data: Attachment payload from Zammad as bytes or a file-like object.
            attachment: The article attachment object.

        Returns:
            The extracted markdown content from the first extraction result.
        """
        document_bytes: bytes = self._coerce_document_bytes(data)

        response: Response = self.client.post(
            "extract",
            data={"output_format": "markdown"},
            files={"files": (attachment.filename, document_bytes, "application/octet-stream")},
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            raise ValueError("Remote Kreuzberg returned an empty or invalid response.")
        first_result = payload[0]
        if not isinstance(first_result, dict):
            raise ValueError("Remote Kreuzberg returned an invalid extraction result.")
        content = first_result.get("content")
        if not isinstance(content, str):
            raise ValueError("Remote Kreuzberg returned an invalid extraction result.")
        logger.info("Successfully sent document to remote Kreuzberg for parsing.")
        return content
