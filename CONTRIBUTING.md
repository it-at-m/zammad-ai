# Contributing to Zammad-AI

Thanks for your interest in contributing! This guide explains how to propose changes, our workflows, and the quality checks required before opening a pull request.

## Code of Conduct

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Project Layout

- `zammad-ai-workflow/` – Backend service (FastAPI + FastStream Kafka)
  - `app/settings/` – Pydantic settings (env prefix `ZAMMAD_AI_`)
  - `app/api/` – REST API (`/api/v1`)
  - `app/kafka/` – Kafka broker setup and handlers
  - `app/triage/` – Triage business logic
  - `app/zammad/` – Zammad client(s)
  - `app/observe/` – Langfuse integration
  - `app/models/` – Pydantic models
  - `app/frontend/` – Optional Gradio developer UI
  - `test/` – Pytest suite for the service
- `zammad-ai-index/` – Knowledge base indexing job
- `docs/` – VitePress documentation (configuration, components, ADRs)

## Getting Started

1. Start local infrastructure from repo root (Kafka, Qdrant, etc.):
   ```bash
   docker compose up -d
   ```
2. Install backend dependencies:
   ```bash
   cd zammad-ai-workflow
   uv sync
   cp config.example.yaml config.yaml
   ```
3. Put secrets into `.env` (see `.env.example`). Do not commit secrets.
4. Run the service locally:
   ```bash
   uv run python main.py
   ```

## Branching & Pull Requests

- Use short, descriptive branch names like `feat/kafka-retry`, `fix/triage-null-category`, `docs/config-guide`.
- Open a PR against `main` when ready; small, focused PRs are easier to review.
- Ensure the PR updates relevant docs under `docs/` when behavior or configuration changes.

## Commit Messages

Follow Conventional Commits:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Types include `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `style`.

Examples:

```
feat(kafka): add support for message retry logic
fix(triage): handle missing request_type gracefully
docs(configuration): update embedding_model key name
```

Note: Commit signing may be required by repository policy; use the CLI if prompted.

## Required Checks (run locally before pushing)

Run from the service directory you changed (e.g., `zammad-ai-workflow/`):

```bash
uv run pytest
uv run ruff format .
uv run ruff check .
uv run ty check
```

Repository targets Python 3.14.4. Lint config: `ruff.toml` (src includes `zammad-ai-workflow`, `zammad-ai-index`).

## Documentation

- The docs site is built from `docs/` via GitHub Actions.
- Keep concrete file path mentions accurate (e.g., `zammad-ai-workflow/app/settings/...`, `app/observe/langfuse.py`).
- Update configuration and component pages when changing settings, env var names, Kafka topics, or module paths.

## Adding Dependencies

- Ask before adding new dependencies to a service `pyproject.toml`.
- Use `uv` for dependency management; versions are pinned.

## Security & Secrets

- Never commit secrets, tokens, or certificates.
- For Kafka mTLS env schema, use cleartext `pkcs12_pw` with base64-encoded `ca_file_base64` and `pkcs12_base64`.
- Prefer `.env` for secrets; configuration files (`config.yaml`) should not contain secrets.

## Style & Logging

- Follow repository linting and formatting (Ruff).
- Use structured, informative logging. In exception handlers, log with `exc_info=True` and do not interpolate exception text.

## Tests

- Place tests under the corresponding service’s `test/` directory.
- Prefer async-friendly tests; use `pytest-asyncio` and FastStream’s `TestKafkaBroker` where applicable.

## Questions

If something is unclear, open an issue or start a draft PR and ask for guidance.
