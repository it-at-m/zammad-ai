"""Support types for Qdrant vector metadata."""

from typing import TypedDict
from uuid import UUID


class QdrantVectorMetadata(TypedDict):
    """Metadata stored alongside Qdrant vectors."""

    id: UUID
    title: str
    content: str
    attachments: dict[str, str] | None
    url: str | None
