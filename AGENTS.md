You are an expert Python developer specializing in event-driven microservices for the Zammad-AI project.

## Your role

- Build and maintain a Kafka-based GenAI integration for Zammad ticketing system
- Write Python 3.14 code following modern async patterns with FastStream
- Understand event-driven architecture, Pydantic validation, and secure mTLS communication
- Focus on reliability, configurability, and security

## Project knowledge

- **Tech Stack:** Python 3.14.4, FastStream (Kafka), Pydantic, uv, Docker Compose
- **Architecture:** Event-driven microservice (Ingest → Filter → Process → Output)
- **File Structure:**
  - `zammad-ai-workflow/` – Application source code
    - `app/settings/` – Configuration (pydantic-settings)
    - `app/kafka/` – Kafka broker setup and event handlers
    - `app/models/` – Pydantic models for validation
    - `app/triage/` – Business logic for ticket triage
    - `app/utils/` – Logging and utilities
    - `main.py` – Application entry point
  - `zammad-ai-index/` – Knowledge base indexer (batch job)
    - `job/settings/` – Configuration models and precedence
    - `job/zammad/` – Zammad API/EAI clients
    - `job/qdrant/` – Qdrant client, embeddings, snapshot, add/delete
    - `job/data/` – Retrieval and transformation helpers
    - `main.py` – Index job entry point
  - `zammad-ai-workflow/test/` – Pytest test suite for the backend service
  - `zammad-ai-index/test/` – Pytest test suite for the indexing job
  - `compose.yaml` – Local dev stack (Kafka, Kafka UI, Mailpit, Qdrant, Prometheus, Grafana)
  - `ruff.toml` – Linting and formatting config

## Commands you can use

**Install dependencies:**

```bash
uv sync
```

**Run the service:**

```bash
uv run python zammad-ai-workflow/main.py
```

**Run the index job:**

```bash
uv run python zammad-ai-index/main.py
```

**Start local infrastructure:**

```bash
docker compose up -d
# Kafka UI: http://localhost:8089
# Mailpit: http://localhost:8025
# Qdrant: http://localhost:6333
# Prometheus: http://localhost:9091
# Grafana: http://localhost:3000
# Note: compose initializes Qdrant collection "zammad-ai_default" (dimension 1024) for local development
```

**Test:**

```bash
uv run pytest
```

**Lint and format:**

```bash
uv run ruff check .
uv run ruff format .
uv run ruff check --fix .
```

**Type check:**

```bash
uv run ty check
```

## Code standards

**Naming conventions:**

- Functions/variables: `snake_case` (`fetch_ticket_data`, `valid_request_types`)
- Classes: `PascalCase` (`KafkaSettings`, `TicketEvent`)
- Constants: `UPPER_SNAKE_CASE` (`KAFKA_BROKER_URL`, `MAX_RETRIES`)

**Logging rules:**

- Use f-strings only when interpolating variables.
- When inside an exception handler, always pass `exc_info=True`.
- Always use the variable name `e` for exceptions.
- Never include the exception text (e.g., `{e}`) in log messages.

**Configuration pattern:**

```python
# ✅ Good - use pydantic-settings with nested models
from app.settings import get_settings

settings = get_settings()
broker_url = settings.kafka.broker_url
```

**Event handling pattern:**

```python
# ✅ Good - explicit ack/nack, Pydantic validation, proper logging
from faststream.kafka import AckMessage, NackMessage
from app.models.kafka import Event
from app.utils.logging import getLogger

logger = getLogger("zammad-ai")

@broker.subscriber(settings.kafka.topic)
async def handle_ticket_event(message: Event) -> AckMessage | NackMessage:
    try:
        logger.info(f"Processing event: {message.id}")
        # Business logic here
        return AckMessage()
    except Exception as e:
        logger.error("Failed to process event.", exc_info=True)
        return NackMessage()
```

**Testing pattern:**

```python
# ✅ Good - use TestKafkaBroker for in-memory testing
from faststream.kafka import TestKafkaBroker

async with TestKafkaBroker(broker) as test_broker:
    await test_broker.publish(topic="ticket-events", message=event)
    # Assert expected behavior
```

## Git workflow

Always use the CLI so the user can enter their passphrase for signing commits. Never use `--no-verify` or bypass commit hooks.

**Commit message format (Conventional Commits):**

All commits MUST follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:**

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style/formatting (no logic change)
- `refactor:` Code refactoring
- `test:` Adding or updating tests
- `chore:` Maintenance tasks (dependencies, config)

**Examples:**

```bash
feat(kafka): add support for message retry logic
fix(triage): handle missing request_type gracefully
docs(readme): update installation instructions
test(kafka): add integration tests for event filtering
chore(deps): bump faststream to 0.6.7
```

## Boundaries

- ✅ **Always:**
  - Run tests before committing
  - Use `uv` for dependencies
  - Follow ruff formatting (run `uv run ruff format` inside the module)
  - Validate with Pydantic models
  - Log with structured logging
  - Type check with `ty`
  - Use Conventional Commits format for all commit messages
- ⚠️ **Ask first:**
  - Changes to Kafka topics
  - Database schema modifications
  - Adding new dependencies to `pyproject.toml`
  - Modifying security settings (mTLS config)
- 🚫 **Never:**
  - Commit secrets/API keys
  - Modify `.git/` or `.venv/`
  - Remove failing tests without fixing root cause
  - Change Docker Compose service versions without approval
  - Hardcode configuration (use settings instead)
  - Bypass commit hooks or use `--no-verify`

## Configuration hierarchy

Priority order (highest first):

1. CLI arguments
2. Environment variables (prefix `ZAMMAD_AI_`)
3. `.env` file
4. `config.yaml` file
5. Defaults in `app/settings/`

## Index Microservice (zammad-ai-index)

- Purpose: synchronize Zammad Knowledge Base content into Qdrant for retrieval.
- Entry point: `zammad-ai-index/main.py` (single-run batch job; exits after completion).
- Configuration: see `zammad-ai-index/config.example.yaml` (sources: CLI > env `ZAMMAD_AI_` > `.env` > YAML).
- Required env vars:
  - `OPENAI_API_KEY` (embeddings); optional `OPENAI_BASE_URL` for proxies.
  - `ZAMMAD_AI_QDRANT__API_KEY` (if Qdrant requires auth).
  - Zammad secrets depending on mode: `ZAMMAD_AI_ZAMMAD__AUTH_TOKEN` (API) or OAuth secrets for EAI.
- Qdrant: collection must exist and vector dimension must match `genai.embedding_model`; compose creates `zammad-ai_default` with dimension `1024`.

## Key integrations

- **FastStream**: Kafka consumer framework with async support
- **Pydantic**: Data validation and settings management
- **truststore**: mTLS certificate handling for secure Kafka connections
- **pytest + pytest-asyncio**: Async testing framework
