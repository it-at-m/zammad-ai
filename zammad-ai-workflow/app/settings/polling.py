"""Settings for the polling-based ticket intake feature."""

from pydantic import BaseModel, Field, PositiveInt


class PollingSettings(BaseModel):
    """Settings for polling the Zammad API as an alternative intake to Kafka."""

    enabled: bool = Field(
        description="Whether to enable polling-based ticket intake. Defaults to False.",
        default=False,
    )
    interval_seconds: PositiveInt = Field(
        description="Interval in seconds between polling cycles. Defaults to 60.",
        default=60,
    )
    search_query: str = Field(
        description="Zammad search query used to select tickets for processing.",
        default="state.name:(new OR open)",
    )
    processed_ttl_seconds: PositiveInt = Field(
        description="Time-to-live in seconds for in-memory processed-ticket deduplication entries. Defaults to 3600.",
        default=3600,
    )
    per_page: int = Field(
        description="Number of search results per page. Zammad caps the ticket search at 200.",
        default=50,
        ge=1,
        le=200,
    )
    max_pages: PositiveInt = Field(
        description="Maximum number of search result pages to fetch per polling cycle. Defaults to 1.",
        default=1,
    )
