"""Settings models for ingesting laws into Qdrant."""

from pydantic import BaseModel, Field, HttpUrl, PositiveInt


class LawConfig(BaseModel):
    """Configuration for a single law ingestion source."""

    id: str = Field(description="Stable identifier for the law (e.g. 'fev')", examples=["fev", "stvg"])
    name: str = Field(description="Human readable name of the law", examples=["Fahrerlaubnis-Verordnung"])
    url: HttpUrl = Field(description="Canonical source URL of the law HTML page")
    chunk_size: PositiveInt = Field(default=7500, description="Chunk size for text splitter")
    chunk_overlap: PositiveInt = Field(default=200, description="Chunk overlap for text splitter")
