"""Pydantic models for Qdrant index records."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from job.models.zammad import KnowledgeBaseAttachment


class QdrantVectorMetadata(BaseModel):
    """Metadata stored alongside a Qdrant vector."""

    # vector info
    vector_updatedAt: datetime
    # answer info
    answer_id: int
    answer_kb_id: int
    answer_title: str
    answer_body: str
    answer_createdAt: datetime
    answer_updatedAt: datetime
    answer_attachments: list[KnowledgeBaseAttachment]
    answer_url: str | None
    # hash of page_content
    pagecontent_hash: str | None = None


class QdrantDocumentItem(BaseModel):
    """A Qdrant document item ready for indexing."""

    vector_id: UUID
    page_content: str
    metadata: QdrantVectorMetadata
