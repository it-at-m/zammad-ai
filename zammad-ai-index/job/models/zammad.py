"""Models for Zammad knowledge base answers and attachments."""

from datetime import datetime

from pydantic import BaseModel, Field


class ZammadKnowledgebase(BaseModel):
    """Knowledge base metadata returned by Zammad."""

    id: int = Field(
        description="ID of the knowledge base",
    )
    active: bool = Field(
        description="Whether the knowledge base is active",
        default=True,
    )
    createdAt: datetime = Field(
        description="Creation timestamp of the knowledge base",
    )
    updatedAt: datetime = Field(
        description="Last update timestamp of the knowledge base",
    )
    categoryIds: list[int] = Field(
        description="List of category IDs associated with the knowledge base",
        default_factory=list,
    )
    answerIds: list[int] = Field(
        description="List of answer IDs associated with the knowledge base",
        default_factory=list,
    )


class KnowledgeBaseAttachment(BaseModel):
    """Attachment metadata for a knowledge base answer."""

    id: int = Field(
        description="ID of the attachment",
    )
    filename: str = Field(
        description="Filename of the attachment",
    )
    contentType: str = Field(
        description="Content type of the attachment",
    )


class KnowledgeBaseAnswer(BaseModel):
    """Knowledge base answer payload used by the index job."""

    id: int = Field(
        description="The ID of the answer",
    )
    answerTitle: str = Field(
        description="The title of the answer",
    )
    answerBody: str = Field(
        description="The content of the answer",
    )
    createdAt: datetime = Field(
        description="The creation timestamp of the answer",
    )
    updatedAt: datetime = Field(
        description="The last update timestamp of the answer",
    )
    attachments: list[KnowledgeBaseAttachment] = Field(
        description="List of attachments associated with the answer",
        default_factory=list,
    )
