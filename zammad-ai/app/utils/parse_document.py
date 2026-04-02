"""Helpers for parsing attachment documents through Kreuzberg."""

from asyncio import to_thread
from logging import Logger
from typing import Any

from httpx import AsyncClient, Response
from langchain_core.documents.base import Document
from pydantic import HttpUrl

from app.models.zammad import ArticleAttachment

from .logging import getLogger

logger: Logger = getLogger("zammad-ai.utils.parse_document")
DEFAULT_MIME_TYPE = "application/octet-stream"


async def parse_document_local(data: Any) -> str:
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
    docs: list[Document] = await to_thread(loader.load)
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


async def parse_document_remote(data: Any, url: HttpUrl, attachment: ArticleAttachment, proxy: str | None) -> str:
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

    async with AsyncClient(timeout=120, proxy=proxy, base_url=str(url)) as client:
        response: Response = await client.post(
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
