# Knowledge Base Indexer

`zammad-ai-index` is a batch job that copies Zammad Knowledge Base content into Qdrant.

## Workflow

1. Load configuration and initialize the Zammad and Qdrant clients.
2. Resolve the answer IDs to process, either in full or incremental mode.
3. Fetch the answer content from Zammad.
4. Transform the content into Qdrant documents.
5. Compare the result with existing Qdrant points.
6. Create a snapshot before writing changes.
7. Upsert changed documents and delete obsolete ones.

## Configuration

Relevant settings live under:

- `index`
- `genai`
- `zammad`
- `qdrant`
- `laws`

## Runtime Notes

- The job runs once and exits.
- Snapshot creation happens before any write.
- The same Qdrant collection can be used for knowledge base content and optional law ingestion.
