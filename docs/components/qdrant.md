# Qdrant Vector Database

The project uses Qdrant for retrieval in the answer pipeline and for indexing Zammad knowledge base content.

## Integration

The workflow service configures Qdrant under `answer.qdrant`. The index job configures it under `qdrant`.

## Configuration Keys

- `url`: The URL of the Qdrant instance.
- `api_key`: Secret key for authentication.
- `collection_name`: The name of the collection where knowledge vectors are stored.
- `vector_dimension`: The dimensionality of the embeddings.
- `vector_name`: Optional name of the vector configuration in the collection.
- `retrieval_num_documents`: Number of documents to retrieve per query.
- `retrieval_mode`: `dense`, `sparse`, or `hybrid`.
- `sparse_vector_name`: Name of the sparse vector configuration.
- `multi_query.enabled`: Enable multi-query expansion.
- `multi_query.include_original`: Keep the original query in the retrieval set.

## Data Models

The workflow stores answer documents with `title` and `url` fields. The index job stores knowledge base and law metadata in Qdrant payloads.

- Knowledge base entries are compared by content hash before being written.
- Law entries use deterministic IDs and store metadata such as `law_id`, `paragraph`, `annex`, and `chunk`.

## Current Status

The workflow requires Qdrant for answer generation when retrieval is enabled.
The index job requires the target collection to exist before it runs.
