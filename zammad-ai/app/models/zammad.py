import html
import re

from pydantic import AliasChoices, BaseModel, Field, field_validator


class KnowledgeBaseAnswer(BaseModel):
    id: str = Field(
        description="The ID of the answer",
    )
    title: str = Field(
        description="The title of the answer",
    )
    content: str = Field(
        description="The content of the answer",
    )
    attachments: dict[str, str] = Field(
        description="Dict of attachments associated with the filename",
        default_factory=dict,
    )


class ZammadTicket(BaseModel):
    id: str = Field(
        description="Unique identifier for the ticket",
    )
    articles: list["ZammadArticle"] = Field(
        description="List of articles associated with the ticket",
        default_factory=list,
    )


class ZammadArticle(BaseModel):
    id: str = Field(
        description="ID of the article",
    )
    ticket_id: str = Field(
        description="ID of the associated ticket",
    )
    text: str = Field(
        description="Body of the article",
        validation_alias=AliasChoices("text", "body"),
    )
    attachments: list["Attachment"] = Field(
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

    @field_validator("text", mode="after")
    @classmethod
    def strip_html(cls, text: str) -> str:
        """
        Normalize article text by removing HTML tags, unescaping HTML entities, and collapsing whitespace.
        
        Parameters:
            text: Input string that may contain HTML.
        
        Returns:
            The input string with HTML tags removed, HTML entities unescaped, and runs of whitespace collapsed to single spaces and trimmed.
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


class Attachment(BaseModel):
    id: str = Field(
        description="ID of the attachment",
    )
    filename: str = Field(
        description="Filename of the attachment",
    )
    size: str = Field(
        description="Size of the attachment",
    )
    preferences: dict = Field(
        description="Preferences of the attachment",
        default_factory=dict,
    )


class ZammadAnswer(BaseModel):
    ticket_id: str = Field(
        description="ID of the associated ticket",
    )
    body: str = Field(
        description="Content of the article to post",
    )
    internal: bool = Field(
        description="Whether the article should be marked as internal",
        default=False,
    )
    subject: str = "Call note"
    content_type: str = "text/html"
    sender: str = "KI Agent"
    type: str = "phone"
    time_unit: str = "15"