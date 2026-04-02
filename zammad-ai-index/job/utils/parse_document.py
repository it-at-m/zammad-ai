"""Helpers for parsing attachment documents through Kreuzberg."""

from logging import Logger
from typing import Any

from httpx import Client, Response
from langchain_core.documents.base import Document
from pydantic import HttpUrl

from job.models.zammad import KnowledgeBaseAttachment

from .logging import getLogger

logger: Logger = getLogger("zammad-ai-index.utils.parse_document")
DEFAULT_MIME_TYPE = "application/octet-stream"


def parse_document_local(data: Any) -> str:
    """Process attachment content using local Kreuzberg.

    Args:
        data: Attachment payload from Zammad as bytes or a file-like object.

    Returns:
        The extracted document text.
    """
    from langchain_kreuzberg import KreuzbergLoader

    document_bytes: bytes = _coerce_document_bytes(data)
    loader = KreuzbergLoader(
        data=document_bytes,
        mime_type=DEFAULT_MIME_TYPE,
    )
    docs: list[Document] = loader.load()
    if not isinstance(docs, list) or not docs:
        raise ValueError("Kreuzberg did not return any documents for the attachment.")
    logger.info("Successfully processed document with local Kreuzberg.")
    return docs[0].page_content


def _coerce_document_bytes(data: Any) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    if hasattr(data, "read"):
        return _coerce_document_bytes(data.read())
    raise TypeError(f"Unsupported document payload type: {type(data).__name__}")


def parse_document_remote(data: Any, url: HttpUrl, attachment: KnowledgeBaseAttachment, proxy: str | None) -> str:
    """Send attachment content to a remote Kreuzberg API server.

    Args:
        data: Attachment payload from Zammad as bytes or a file-like object.
        url: Kreuzberg API server base URL.
        attachment: The article attachment object.
        proxy: Optional proxy URL for routing requests.

    Returns:
        The extracted markdown content from the first extraction result.
    """
    document_bytes = _coerce_document_bytes(data)

    with Client(timeout=120, proxy=proxy) as client:
        response: Response = client.post(
            url=f"{url}/extract",
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
