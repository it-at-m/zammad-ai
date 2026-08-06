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
    retrieval_mode: str = Field(
        description="Retrieval mode for QdrantVectorStore. One of 'dense', 'sparse' or 'hybrid'. When 'sparse' or 'hybrid' are selected a compatible sparse embedding implementation (e.g. FastEmbedSparse) must be available in the environment.",
        default="dense",
        examples=["dense", "sparse", "hybrid"],
    )
    sparse_vector_name: str = Field(
        description="Name of the sparse vector configuration in the Qdrant collection (used when retrieval_mode is 'sparse' or 'hybrid').",
        default="langchain-sparse",
    )
    bm25_enabled: bool = Field(
        description="Whether to enable BM25-based text scoring on the Qdrant side when using hybrid search. Qdrant server must have text search enabled/configured.",
        default=False,
    )
