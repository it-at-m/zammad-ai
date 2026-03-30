"""Settings for the indexing job."""

from pydantic import BaseModel, Field, PositiveInt


class IndexJobSettings(BaseModel):
    """Settings for fetching and processing knowledge base answers."""

    full_indexing: bool = Field(
        description="Whether to perform a full indexing of all knowledge base answers. If False, only answers updated within the specified interval will be indexed.",
        default=False,
    )
    interval: PositiveInt = Field(
        description="Interval in days to look back for updated answers when fetching from Zammad.",
        default=7,
    )
    batch_size: PositiveInt = Field(
        description="Number of documents to process in each batch when adding to Qdrant.",
        default=50,
    )
