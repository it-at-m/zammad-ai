# Qdrant Vector Database

The project uses Qdrant as a vector database for knowledge retrieval and semantic search. This component is used to manage and query relevant information to augment the context of GenAI requests.

## Integration

The Qdrant integration is configured via `app.settings.answer.QdrantSettings` (nested under the `answer` settings). It uses the `langchain-qdrant` package to provide a vector store compatible with LangChain chains.

## Configuration Keys

- `host`: The URL of the Qdrant instance.
- `api_key`: Secret key for authentication.
- `collection_name`: The name of the collection where knowledge vectors are stored.
- `vector_dimension`: The dimensionality of the embeddings (defaults to 1024, matching common models like `text-embedding-3-large`).
- `retrieval_mode`: One of `dense`, `sparse` or `hybrid`. When selecting `sparse` or `hybrid` the QdrantVectorStore requires a compatible sparse embedding implementation and a collection configured with sparse vectors, such as FastEmbedSparse.
- `sparse_vector_name`: Name of the sparse vector configuration in the Qdrant collection (defaults to `langchain-sparse`).

## Data Models

The `QdrantVectorMetadata` model in `zammad-ai-workflow/app/models/qdrant.py` defines the structure of the metadata stored alongside vectors:

- `id`: Unique identifier (e.g., Zammad article ID).
- `title`: Title of the source content.
- `content`: The raw text content.
- `attachments`: Optional references to associated files.

## Current Status

Currently, the Qdrant integration is primarily used for the (planned) Knowledge Management system, where updates from Zammad (e.g., via RSS feed) are indexed into the vector store.
