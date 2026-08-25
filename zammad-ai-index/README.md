# zammad-ai-index

`zammad-ai-index` is a single-run indexing job that synchronizes Zammad Knowledge Base content into Qdrant.
It is used by the answer pipeline to keep retrieval content current.

## Architecture Overview

- `job/zammad/*` fetches knowledge base data from Zammad via REST API (`api.py`) or EAI (`eai.py`).
- `job/data/*` retrieves IDs and transforms answers into Qdrant document items.
- `job/law/*` can ingest configured law sources into the same collection.
- `job/qdrant/qdrant.py` manages Qdrant client setup, embeddings, snapshots, add/delete operations.
- `job/settings/*` contains Pydantic settings and configuration precedence.

## Purpose

The job runs once and exits, so it can be scheduled by cron, a systemd timer, or a Kubernetes CronJob. During a run it:

- indexes new or updated knowledge base content
- removes content from Qdrant that no longer exists in Zammad
- avoids unnecessary re-indexing through change detection

## Processing Flow

The indexing run follows a fixed, fault-tolerant workflow:

1. Determine relevant answer IDs from Zammad (full or incremental mode)
2. Retrieve the corresponding answer data
3. Transform content into the internal Qdrant document format
4. Compare against existing Qdrant points to detect changes
5. Create a Qdrant snapshot before writing
6. Write new or updated documents in batches
7. Remove obsolete Qdrant points that no longer exist in Zammad

## Prerequisites

- Python 3.14.4
- uv as dependency and execution tool
- reachable Qdrant server
- valid Zammad credentials
- OpenAI env vars for embeddings

## Setup

1. Change to the project directory.

```bash
cd zammad-ai-index
```

2. Install dependencies.

```bash
uv sync
```

3. Create the configuration file.

```bash
cp config.example.yaml config.yaml
```

4. Configure values in config.yaml.

At minimum, configure:

- Zammad connection settings
- Qdrant connection settings
- index parameters such as batch size
- `genai.embedding_model` and the corresponding `OPENAI_API_KEY`

Recommended: keep secrets in `.env` and non-secret defaults in `config.yaml`.

Typical environment variables (.env):

```env
# OpenAI embeddings
OPENAI_API_KEY=...
# Optional for custom endpoint/proxy
# OPENAI_BASE_URL=...

# Qdrant
ZAMMAD_AI_QDRANT__API_KEY=...

# Zammad (API mode)
ZAMMAD_AI_ZAMMAD__AUTH_TOKEN=...

# Zammad (EAI mode)
# ZAMMAD_AI_ZAMMAD__OAUTH2_CLIENT_SECRET=...
# ZAMMAD_AI_ZAMMAD__OAUTH2_CLIENT_ID=...
# ZAMMAD_AI_ZAMMAD__OAUTH2_TOKEN_URL=...
```

## Run

```bash
uv run python main.py
```

Notes:

- The job exits without writing if no new or changed documents are detected.
- A Qdrant collection snapshot is created before any write; snapshot failure aborts the run.
- The job supports both Zammad API and EAI authentication modes.

## Law Ingestion (Experimental)

You can ingest legal texts (e.g., FeV) into the same Qdrant collection using the shared embeddings/Qdrant setup. Configure one or more laws in `config.yaml` under the `laws:` section (see `config.example.yaml`), then run:

```bash
uv run python main.py
```

Notes:

- Documents are chunked and written with metadata including `source=law`, `law_id`, `document_type`, `law_name`, `paragraph`, `chunk`, `pagecontent_hash`, and `law_url` (the configured source URL).
- The `law_url` metadata stores the canonical URL that was used to fetch the law; this helps traceability and auditing of indexed legal text.
- Deterministic IDs are generated per paragraph chunk to upsert documents on subsequent runs.
- A snapshot is created before writing; snapshot failure aborts the run.
- `document_type` is either law or annex.

## Qdrant Prerequisites

- The target collection must exist and have a vector size matching your `genai.embedding_model`.
- In this repository, `compose.yaml` provisions Qdrant and an init job that creates the default collection `zammad-ai_default` with dimension `1024` for local development.
- If you do not use the provided compose stack, ensure the collection exists and vector size matches `qdrant.vector_dimension`.

## Configuration

Settings source priority (highest first):

1. CLI arguments
2. Environment variables (`ZAMMAD_AI_` prefix)
3. `.env`
4. `config.yaml`

Key sections (see `config.example.yaml` for a full example):

- `index`: `full_indexing`, `interval`, `batch_size`
- `genai`: `sdk`, `chat_model`, `embedding_model`, `max_retries`
- `qdrant`: `url`, `api_key`, `collection_name`, `vector_name`, `vector_dimension`, `timeout`, `retrieval_num_documents`
- `zammad`: `type` (`api` or `eai`), `base_url`, `knowledge_base_id`, auth fields, optional RSS feed token/locale, and `document_parsing` (`mode`, `url`, `http_proxy_url`, `document_types`)
- `laws` (optional): list of law sources with `id`, `name`, `url`, `chunk_size`, `chunk_overlap`
- `mode`: `production`, `development`, or `unittest`
- `langfuse_enabled`: enable or disable tracing/prompt lookup

## Modes

- `development`: local-friendly structlog console output and behavior
- `production`: production defaults
- `unittest`: test mode

Set mode via config or env, for example:

```bash
export ZAMMAD_AI_MODE=development
```

## Runtime Behavior

- The run exits without writing if no new or updated documents are detected.
- If snapshot creation fails, the run is aborted before any update is written.
- Connections to Zammad and Qdrant are closed in a controlled way at the end of the run.

## Testing and Quality

Run from this service directory (`zammad-ai-index/`):

```bash
uv run ruff check .
uv run ruff format .
uv run ty check
```

## Scheduling (Minimal)

Run the job on a schedule using your platform’s scheduler (cron, systemd timer, Kubernetes CronJob). The process runs once and exits.
