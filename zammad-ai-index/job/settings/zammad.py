"""Settings for Zammad connectivity in the index job."""

from abc import ABC
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, NonNegativeInt, PositiveInt, SecretStr, model_validator

ZammadEndpoint = Literal["api", "eai"]

KREUZBERG_DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
        "pdf",
        "docx",
        "docm",
        "dotx",
        "dotm",
        "dot",
        "doc",
        "pptx",
        "pptm",
        "ppsx",
        "potx",
        "potm",
        "pot",
        "ppt",
        "odt",
        "xlsx",
        "xlsm",
        "xlsb",
        "xls",
        "xlam",
        "xla",
        "xltx",
        "xlt",
        "ods",
        "dbf",
        "hwp",
        "hwpx",
        "pages",
        "numbers",
        "key",
        "txt",
        "md",
        "markdown",
        "html",
        "htm",
        "xml",
        "svg",
        "rst",
        "org",
        "rtf",
        "djot",
        "mdx",
        "json",
        "yaml",
        "yml",
        "toml",
        "csv",
        "tsv",
        "eml",
        "msg",
        "png",
        "jpg",
        "jpeg",
        "webp",
        "bmp",
        "tiff",
        "tif",
        "gif",
        "jp2",
        "jpx",
        "jpm",
        "mj2",
        "jbig2",
        "jb2",
        "pnm",
        "pbm",
        "pgm",
        "ppm",
        "zip",
        "tar",
        "tgz",
        "7z",
        "gz",
        "tex",
        "latex",
        "epub",
        "bib",
        "typst",
        "typ",
        "ipynb",
        "fb2",
        "docbook",
        "dbk",
        "jats",
        "opml",
        "ris",
        "enw",
        "nbib",
        "csl",
        "mdoc",
        "troff",
        "pod",
        "dokuwiki",
    }
)


class DocumentParsingSettings(BaseModel):
    """Settings for parsing documents retrieved from Zammad."""

    mode: Literal["off", "local", "remote"] = Field(
        description="Mode for parsing documents retrieved from Zammad. 'off' to disable parsing, 'local' to use local Kreuzberg, 'remote' to send documents to a remote Kreuzberg API.",
        default="off",
    )

    url: HttpUrl | None = Field(
        description="Optional URL to send documents for remote parsing. If not set, local parsing will be used.",
        default=None,
    )

    http_proxy_url: str | None = Field(
        description="Optional proxy URL for routing requests to remote Kreuzberg API through a proxy server.",
        default=None,
    )
    document_types: list[str] = Field(
        description="List of document types to parse from Zammad attachments, e.g. ['pdf', 'docx'].",
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_document_types(self) -> "DocumentParsingSettings":
        """Validate that all specified document types are supported."""
        if self.mode != "off" and self.document_types:
            unsupported_types: list[str] = sorted(set(self.document_types) - KREUZBERG_DOCUMENT_TYPES)
            if unsupported_types:
                raise ValueError(
                    "Unsupported document types specified: "
                    f"{unsupported_types}. Supported types are: {sorted(KREUZBERG_DOCUMENT_TYPES)}"
                )
        return self

    @model_validator(mode="after")
    def validate_url(self) -> "DocumentParsingSettings":
        """Validate that URL is set when mode is 'remote'."""
        if self.mode == "remote" and not self.url:
            raise ValueError("URL must be set for remote parsing mode.")
        return self


class BaseZammadSettings(BaseModel, ABC):
    """Base settings for Zammad integration."""

    knowledge_base_id: int = Field(
        description="The ID of the knowledge base to use for retrieving documents.",
        examples=[1],
    )
    category_ids: list[PositiveInt] = Field(
        description="List of category IDs to filter documents by. If empty, documents from all categories will be retrieved.",
        default_factory=list,
        examples=[[1, 2, 3]],
    )
    timeout: int = Field(
        description="HTTP timeout in seconds for requests to Zammad.",
        default=30,
        ge=5,
    )
    max_retries: NonNegativeInt = Field(
        description="Maximum number of retries for HTTP requests to Zammad in case of failures.",
        default=3,
    )
    http_proxy_url: str | None = Field(
        description="Optional proxy URL for routing HTTP requests to Zammad through a proxy server.",
        default=None,
    )
    base_url: HttpUrl = Field(
        description="Zammad base URL",
        examples=["https://my-zammad.example.com"],
    )

    document_parsing: DocumentParsingSettings = Field(
        description="Settings for parsing documents retrieved from Zammad.",
        default_factory=DocumentParsingSettings,
    )


class ZammadAPISettings(BaseZammadSettings):
    """Settings for Zammad API integration."""

    type: Literal["api"] = "api"

    auth_token: SecretStr = Field(
        description="Zammad API authentication token",
    )
    rss_feed_token: SecretStr | None = Field(
        description="RSS feed token",
        default=None,
    )
    rss_feed_locale: str = Field(
        description="Locale for RSS feed (e.g., 'de-de')",
        default="de-de",
    )


class ZammadEAISettings(BaseZammadSettings):
    """Settings for Zammad EAI integration."""

    type: Literal["eai"] = "eai"

    eai_url: HttpUrl = Field(
        description="Zammad EAI API endpoint",
        examples=["https://my-zammad-eai.example.com/api/v1"],
    )

    # OAuth 2.0 Client Credentials Flow settings
    oauth2_client_id: str = Field(
        description="OAuth 2.0 client identifier for authentication",
    )
    oauth2_client_secret: SecretStr = Field(
        description="OAuth 2.0 client secret for authentication",
    )
    oauth2_token_url: HttpUrl = Field(
        description="OAuth 2.0 token endpoint URL",
        examples=["https://my-zammad-eai.example.com/oauth/token"],
    )
    oauth2_scope: str | None = Field(
        description="OAuth 2.0 scope for requesting specific permissions",
        default=None,
    )
