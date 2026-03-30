"""Settings for Zammad connectivity in the index job."""

from abc import ABC
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, NonNegativeInt, SecretStr

ZammadEndpoint = Literal["api", "eai"]


class BaseZammadSettings(BaseModel, ABC):
    """Base settings for Zammad integration."""

    knowledge_base_id: int = Field(
        description="The ID of the knowledge base to use for retrieving documents.",
        examples=[1],
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
