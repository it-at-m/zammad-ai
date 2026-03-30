"""Settings for Qdrant connectivity and retrieval in the index job."""

from pydantic import BaseModel, Field, HttpUrl, PositiveInt, SecretStr


class QdrantSettings(BaseModel):
    """Settings for Qdrant vector database integration and retrieval."""

    url: HttpUrl = Field(
        description="Qdrant host URL",
        default=HttpUrl(url="http://localhost:6333"),
        examples=["https://qdrant.example.com:6333"],
    )
    api_key: SecretStr | None = Field(
        description="Qdrant API key; always use API keys in production for secure access",
        default=None,
        examples=["sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    )
    collection_name: str = Field(
        description="Qdrant collection name",
        default="zammad-ai_default",
        examples=["zammad-ai_my-topic"],
    )
    vector_name: str = Field(
        description="Qdrant vector name (used for namespacing vectors, optional)",
        default="",
    )
    vector_dimension: PositiveInt = Field(
        description="Dimension of the embeddings stored in Qdrant",
        default=1024,
    )
    timeout: PositiveInt = Field(
        description="Timeout in seconds for Qdrant client operations",
        default=60,
    )
    retrieval_num_documents: PositiveInt = Field(
        description="The number of relevant documents to retrieve for each search query.",
        default=5,
    )
