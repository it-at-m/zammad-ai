"""Helpers for parsing attachment documents through Kreuzberg."""

from base64 import b64decode
from binascii import Error
from json import loads
from logging import Logger
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from job.models.zammad import KnowledgeBaseAttachment

from .logging import getLogger

logger: Logger = getLogger("zammad-ai-index.utils.parse_document")


def parse_document(data: Any, attachment: KnowledgeBaseAttachment, url: str | None) -> str:
    """Parse attachment content using remote Kreuzberg when configured.

    Args:
        data: Attachment payload from Zammad, typically bytes or a base64 string.
        attachment: The knowledge base attachment object.
        url: Optional Kreuzberg API server URL.

    Returns:
        The extracted document text.
    """
    if url:
        return send_to_remote_kreuzberg(data, url, attachment)
    return local_kreuzberg_processing(data, attachment)


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


def _build_multipart_body(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary: str = uuid4().hex
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    for name, (filename, content, content_type) in files.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8"),
                content,
                b"\r\n",
            ]
        )

    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send_to_remote_kreuzberg(data: Any, url: str, attachment: KnowledgeBaseAttachment) -> str:
    """Send attachment content to a remote Kreuzberg API server.

    Args:
        data: Attachment payload from Zammad.
        url: Kreuzberg API server base URL.
        attachment: The knowledge base attachment object.

    Returns:
        The extracted markdown content from the first extraction result.
    """
    document_bytes = _coerce_document_bytes(data)
    body, content_type = _build_multipart_body(
        {"output_format": "markdown"},
        {"files": (attachment.filename, document_bytes, attachment.contentType)},
    )

    request = Request(
        f"{url}/extract",
        data=body,
        headers={"Content-Type": content_type, "Accept": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            payload = loads(response.read().decode("utf-8"))
    except (HTTPError, URLError):
        raise

    logger.info("Successfully sent document to remote Kreuzberg for parsing.")
    return payload[0]["content"]


def local_kreuzberg_processing(data: Any, attachment: KnowledgeBaseAttachment) -> str:
    """Process attachment content using local Kreuzberg.

    Args:
        data: Attachment payload from Zammad, typically bytes or a base64 string.
        attachment: The knowledge base attachment object.

    Returns:
        The extracted document text.
    """
    from langchain_kreuzberg import KreuzbergLoader

    document_bytes: bytes = _coerce_document_bytes(data)
    loader = KreuzbergLoader(
        data=document_bytes,
        mime_type=attachment.contentType,
    )
    docs = loader.load()
    if not docs:
        raise ValueError("Kreuzberg did not return any documents for the attachment.")
    logger.info("Successfully processed document with local Kreuzberg.")
    return docs[0].page_content
