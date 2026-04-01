"""Helpers for parsing attachment documents through Kreuzberg."""

from base64 import b64decode
from binascii import Error
from logging import Logger
from typing import Any

from httpx import AsyncClient

from app.models.zammad import ArticleAttachment

from .logging import getLogger

logger: Logger = getLogger("zammad-ai-index.utils.parse_document")


async def parse_document_local(data: Any) -> str:
    """Process attachment content using local Kreuzberg.

    Args:
        data: Attachment payload from Zammad, typically bytes or a base64 string.
        attachment: The article attachment object.

    Returns:
        The extracted document text.
    """
    from langchain_kreuzberg import KreuzbergLoader

    document_bytes: bytes = _coerce_document_bytes(data)
    loader = KreuzbergLoader(
        data=document_bytes,
        mime_type="application/octet-stream",
    )
    docs = loader.load()
    if not docs:
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
        return data.read()
    if isinstance(data, str):
        try:
            return b64decode(data, validate=True)
        except (ValueError, Error):
            return data.encode("utf-8")
    raise TypeError(f"Unsupported document payload type: {type(data).__name__}")


async def parse_document_remote(data: Any, url: str, attachment: ArticleAttachment, proxy: str | None) -> str:
    """Send attachment content to a remote Kreuzberg API server.

    Args:
        data: Attachment payload from Zammad.
        url: Kreuzberg API server base URL.
        attachment: The article attachment object.
        proxy: Optional proxy URL for routing requests.

    Returns:
        The extracted markdown content from the first extraction result.
    """
    document_bytes = _coerce_document_bytes(data)

    async with AsyncClient(timeout=120, proxy=proxy) as client:
        response = await client.post(
            f"{url}/extract",
            data={"output_format": "markdown"},
            files={"files": (attachment.filename, document_bytes, "application/octet-stream")},
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()

    logger.info("Successfully sent document to remote Kreuzberg for parsing.")
    return payload[0]["content"]
