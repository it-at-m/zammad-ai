# zammad-ai

zammad-ai is the backend microservice for ticket triage, answer generation, and event-driven processing in the Zammad-AI ecosystem.

It provides:

- REST endpoints for triage and answer generation
- Kafka consumer processing for ticket events
- Retrieval-augmented answer generation with Qdrant
- Optional embedded frontend for local usage
- Prometheus metrics for observability

## Prerequisites

- Python 3.14.4
- uv
- Optional for local full stack: Docker + Docker Compose

## Project Structure

- `app/api/` API routing and backend app wiring
- `app/triage/` ticket categorization and action selection logic
- `app/answer/` answer generation and retrieval logic
- `app/kafka/` broker setup and event handlers
- `app/settings/` typed settings models and source precedence
- `test/` pytest test suite

## Setup

1. Switch into the service directory:

```bash
cd zammad-ai
```

2. Install dependencies:

```bash
uv sync
```

3. Create local configuration:

```bash
cp config.example.yaml config.yaml
```

4. Put secrets into `.env` (recommended) and adapt `config.yaml` values.

## Run

Run the backend:

```bash
uv run main.py
```

Default behavior:

- HTTP server runs on port `8080`
- In `development` mode, docs are available at `/api/docs`
- If frontend is disabled in `development`, `/` redirects to `/api/docs`

## API

Public endpoints:

- `GET /api/v1/health`
- `POST /api/v1/triage`
- `POST /api/v1/answer`

The OpenAPI UI is available at:

- `http://localhost:8080/api/docs` (development mode)

## Optional Frontend

Enable in `config.yaml`:

```yaml
frontend:
	enabled: true
```

When enabled, the frontend is mounted at `/` and calls the same `/api/v1/*` endpoints.

## Configuration

Settings source priority (highest first):

1. CLI arguments
2. Environment variables (`ZAMMAD_AI_` prefix)
3. `.env`
4. `config.yaml`

Notes:

- Keep secrets in `.env`, not in `config.yaml`
- Nested settings use `__`, for example `ZAMMAD_AI_KAFKA__BROKER_URL`
- For local compose Kafka access, default is typically `localhost:29092`

## Local Development Stack

From repository root, start infrastructure:

```bash
docker compose up -d
```

Common local services:

- Kafka UI: `http://localhost:8089`
- Mailpit: `http://localhost:8025`
- Qdrant: `http://localhost:6333`
- Prometheus: `http://localhost:9091`
- Grafana: `http://localhost:3000`

## Testing and Quality

Run from this service directory (`zammad-ai/`):

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run ty check
```

## Notes

- The service must not run in `unittest` mode; startup exits with error in that mode.
- Prometheus metrics exporter can be enabled/disabled via settings.
