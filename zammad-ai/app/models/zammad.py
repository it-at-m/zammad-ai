"""Models for Zammad knowledge base, tickets, and answer payloads."""

import html
import re
from datetime import datetime

from pydantic import AliasChoices, BaseModel, Field, field_validator


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
    """Knowledge base answer with normalized HTML-free body text."""

    id: int = Field(
        description="The ID of the answer",
    )
    answerTitle: str = Field(
        description="The title of the answer",
    )
    answerBody: str = Field(
        description="The content of the answer",
    )
    createdAt: str = Field(
        description="The creation timestamp of the answer",
    )
    updatedAt: str = Field(
        description="The last update timestamp of the answer",
    )
    attachments: list[KnowledgeBaseAttachment] = Field(
        description="List of attachments associated with the answer",
        default_factory=list,
    )

    @field_validator("answerBody", mode="after")
    @classmethod
    def strip_html(cls, text: str) -> str:
        """Normalize text by removing HTML tags, unescaping HTML entities, and collapsing whitespace.

        Parameters:
            text (str): Input string that may contain HTML.

        Returns:
            str: The input string with HTML tags removed, HTML entities unescaped, and consecutive whitespace collapsed to single spaces and trimmed.
        """
        # Remove HTML tags
        clean_text: str = re.sub(
            pattern=r"<[^>]+>",
            repl="",
            string=text,
        )
        # Unescape HTML entities
        clean_text = html.unescape(clean_text)
        # Normalize whitespace
        clean_text = re.sub(
            pattern=r"\s+",
            repl=" ",
            string=clean_text,
        ).strip()
        return clean_text


class ZammadTicket(BaseModel):
    """Ticket model with its associated articles."""

    id: int = Field(
        description="Unique identifier for the ticket",
    )
    articles: list["ZammadArticle"] = Field(
        description="List of articles associated with the ticket",
        default_factory=list,
    )


class ArticleAttachment(BaseModel):
    """Attachment metadata for a ticket article."""

    id: int = Field(
        description="ID of the attachment",
    )
    filename: str = Field(
        description="Filename of the attachment",
    )


class ZammadArticle(BaseModel):
    """Ticket article with body text and attachments."""

    id: int = Field(
        description="ID of the article",
    )
    ticket_id: int = Field(
        description="ID of the associated ticket",
    )
    text: str = Field(
        description="Body of the article",
        validation_alias=AliasChoices("text", "body"),
    )
    attachments: list["ArticleAttachment"] = Field(
        description="List of attachments for the article",
        default_factory=list,
    )
    internal: bool = Field(
        description="Whether the article is internal",
        default=False,
    )
    author: str = Field(
        description="Author of the article",
        default="-",
    )
    subject: str | None = Field(
        description="Subject of the article",
        default=None,
    )

    @field_validator("text", mode="after")
    @classmethod
    def strip_html(cls, text: str) -> str:
        """Normalize article text by removing HTML tags, unescaping HTML entities, and collapsing whitespace.

        Args:
            text: Input string that may contain HTML.

        Returns:
            The input string with HTML tags removed, HTML entities unescaped,
            and runs of whitespace collapsed to single spaces and trimmed.
        """
        # Remove HTML tags
        clean_text: str = re.sub(
            pattern=r"<[^>]+>",
            repl="",
            string=text,
        )
        # Unescape HTML entities
        clean_text = html.unescape(clean_text)
        # Normalize whitespace
        clean_text = re.sub(
            pattern=r"\s+",
            repl=" ",
            string=clean_text,
        ).strip()
        return clean_text


class ZammadAnswer(BaseModel):
    """Answer payload posted back to Zammad."""

    ticket_id: int = Field(
        description="ID of the associated ticket",
    )
    body: str = Field(
        description="Content of the article to post",
    )
    internal: bool = Field(
        description="Whether the article should be marked as internal",
        default=False,
    )
    subject: str | None = Field(default=None, description="Optional subject line for the answer")
    content_type: str = "text/html"


class ZammadTagAdd(BaseModel):
    """Tag assignment payload for a ticket."""

    item: str = Field(description="The tag name")
    object: str = Field(default="Ticket", description="The object type, usually 'Ticket'")
    o_id: int = Field(description="The ID of the object (e.g., ticket ID)")


# TODO: Research good defaults for model values
class ZammadSharedDraftArticle(BaseModel):
    """Shared draft article payload for Zammad EAI."""

    body: str = Field(description="The body of the shared draft")
    cc: str = ""
    content_type: str = "text/html"
    sender: str = Field(default="KI Agent", alias="from")
    in_reply_to: str = ""
    internal: bool = True
    sender_id: int = 1
    subject: str = ""
    subtype: str = ""
    ticket_id: int = Field(description="The ID of the ticket")
    to: str = ""
    type: str = "note"
    type_id: int = 10

    model_config = {"populate_by_name": True}


# TODO: Research good defaults for model values
class ZammadAPISharedDraft(BaseModel):
    """Shared draft wrapper for the Zammad API transport."""

    form_id: str = "367646073"
    new_article: ZammadSharedDraftArticle
    ticket_attributes: dict[str, str] = Field(
        default_factory=lambda: {
            "group_id": "2",
            "owner_id": "4",
            "priority_id": "2",
            "state_id": "2",
        }
    )


class ZammadEAISharedDraft(BaseModel):
    """Shared draft payload for the Zammad EAI transport."""

    body: str = Field(description="The body of the shared draft")
