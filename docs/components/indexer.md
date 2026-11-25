# Knowledge Base Indexer

`zammad-ai-index` is a batch job that copies Zammad Knowledge Base content into Qdrant.

## Workflow

1. Load configuration and resolve the indexing targets.
2. For each target, initialize the Zammad and Qdrant clients.
3. Resolve the answer IDs to process, either in full or incremental mode.
4. Fetch the answer content from Zammad.
5. Transform the content into Qdrant documents.
6. Compare the result with existing Qdrant points.
7. Create a snapshot before writing changes.
8. Upsert changed documents and delete obsolete ones.

## Configuration

Relevant settings live under:

- `index`
- `genai`
- `zammad` (shared connection settings)
- `qdrant` (shared connection settings)
- `targets` (required, see below)

## Indexing Targets

What gets indexed is defined by the required `targets` list — one target per
Qdrant collection. A deployment with a single usecase defines exactly one
target; each target indexes one Zammad knowledge base (or a subset of
categories) into its own collection during a single job run.

Each target may override `qdrant` (e.g. `collection_name`) and `zammad`
(e.g. `knowledge_base_id`, `category_ids`) and defines its own `laws`;
unspecified fields are inherited from the root configuration. Every target
must resolve to a collection name and a knowledge base ID, and target names
and collection names must be unique. A failing target does not stop the
remaining targets; the job exits non-zero if any target failed.

## Runtime Notes

- The job runs once and exits.
- Snapshot creation happens before any write, per target collection.
- A target's collection can be used for both knowledge base content and law ingestion.
