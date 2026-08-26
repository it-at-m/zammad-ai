# Configuration Guide

Zammad-AI uses pydantic-settings with YAML, environment variables, `.env`, and CLI arguments.

## Source Priority

Highest priority first:

1. CLI arguments
2. Environment variables with the `ZAMMAD_AI_` prefix
3. `.env`
4. `config.yaml`
5. Defaults defined in the source code

## Workflow Service

Main settings live in `zammad-ai-workflow/app/settings/` and are loaded by `zammad-ai-workflow/config.example.yaml`.

### Core Sections

- `usecase`: deployment name and description
- `genai`: model provider, chat model, embedding model, and retry settings
- `zammad`: REST API or EAI connection settings, knowledge base ID, and document parsing config
- `kafka`: broker URL, topic names, retry policy, client ID, group ID, and mTLS security
- `triage`: categories, actions, rules, prompt sources, and fallback behavior
- `answer`: answer prompts, Qdrant settings, optional DLF integration, judge settings, and law tools
- `frontend`: optional Gradio UI and feedback settings
- `api`: API key and graceful shutdown timeout
- `prometheus`: metrics server toggle and port
- `guardrails`: remote `slm-guardrails` client settings used by the workflow (`enabled`, `base_url`, `request_timeout_seconds`, `auth_token`, `verify_tls`, `confidence_threshold`, `model`)
- `log`: log format and level
- `preparser`: optional preprocessing before LLM calls
- `max_user_text_length`: input truncation limit
- `recursion_limit`: agent recursion cap
- `mode`: `production`, `development`, or `unittest`

### Common Secrets

```env
OPENAI_API_KEY=...
ZAMMAD_AI_API__API_KEY=...
ZAMMAD_AI_ZAMMAD__AUTH_TOKEN=...
ZAMMAD_AI_QDRANT__API_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=...
```

Guardrails service secrets:

```env
ZAMMAD_AI_GUARDRAILS__AUTH_TOKEN=...
SLM_GUARDRAIL_API__AUTH_TOKEN=...
```

## Index Job

Main settings live in `zammad-ai-index/job/settings/` and are loaded by `zammad-ai-index/config.example.yaml`.

### Core Sections

- `index`: full vs incremental indexing, look-back interval, and batch size
- `genai`: embedding/chat model provider settings
- `zammad`: REST API or EAI connection settings
- `qdrant`: collection URL, API key, collection name, vector dimension, and retrieval options
- `laws`: optional law sources to ingest into the same Qdrant collection
- `log`: log format and level
- `mode`: `production`, `development`, or `unittest`

### Common Secrets

```env
OPENAI_API_KEY=...
ZAMMAD_AI_QDRANT__API_KEY=...
ZAMMAD_AI_ZAMMAD__AUTH_TOKEN=...
ZAMMAD_AI_ZAMMAD__OAUTH2_CLIENT_SECRET=...
```

## Notes

- Keep secrets out of `config.yaml`.
- Use double underscores for nested environment overrides, for example `ZAMMAD_AI_KAFKA__BROKER_URL`.
- The workflow service defaults to Kafka port `9092`, the backend port `8080`, and Prometheus port `9090`.
- The workflow service calls the guardrails service at `http://localhost:8081` by default.
- The index job expects the Qdrant collection to exist and match the configured embedding dimension.
