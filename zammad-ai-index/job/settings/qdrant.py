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
        default="dense",
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
    enable_hybrid_search: bool = Field(
        description="Enable hybrid search (vector + BM25/text) in Qdrant retrieval. When enabled the retriever will use search_type='hybrid' and respect hybrid_alpha.",
        default=False,
    )
    hybrid_alpha: float = Field(
        description="Weighting factor for hybrid search: 0.0 = pure vector, 1.0 = pure text/BM25. Typical default is 0.5.",
        default=0.5,
        ge=0.0,
        le=1.0,
    )
    bm25_enabled: bool = Field(
        description="Whether to enable BM25-based text scoring on the Qdrant side when using hybrid search. Qdrant server must have text search enabled/configured.",
        default=False,
    )
