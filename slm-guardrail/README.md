# slm-guardrail

FastAPI microservice providing content safety guardrails for Zammad-AI. It classifies user prompts and generated responses using a GLiNER-based model and exposes simple REST endpoints. It replaces any in-process guardrail logic in zammad-ai-workflow.

## Features

- REST API with JSON requests and responses
- Prompt and response safety checks
- Prometheus metrics at `/metrics`
- Health endpoint at `/healthz`
- Optional Bearer token authentication
- Offline model mode with Hugging Face cache directory

## API

- GET `/healthz`
- GET `/metrics`
- POST `/api/v1/guardrails/prompt`
- POST `/api/v1/guardrails/response`

### Request and Response Shapes

POST `/api/v1/guardrails/prompt` request:

```json
{ "text": "string", "threshold": 0.7 }
```

Response:

```json
{ "prompt_safety": "safe", "prompt_toxicity": [], "jailbreak_detection": [] }
```

POST `/api/v1/guardrails/response` request:

```json
{ "text": "string", "response": "string", "threshold": 0.7 }
```

Response:

```json
{ "response_safety": "safe", "response_toxicity": [], "response_refusal": [] }
```

### Curl Examples

```bash
curl -sS http://localhost:8081/healthz

curl -sS -X POST http://localhost:8081/api/v1/guardrails/prompt \
  -H 'Content-Type: application/json' \
  -d '{"text":"hello","threshold":0.7}'

curl -sS -X POST http://localhost:8081/api/v1/guardrails/response \
  -H 'Content-Type: application/json' \
  -d '{"text":"hello","response":"world","threshold":0.7}'
```

## Configuration

Configure via environment variables (prefix `SLM_GUARDRAIL_`) or `config.yaml`.

- `API__HOST` bind host, default `0.0.0.0`
- `API__PORT` bind port, default `8081`
- `API__AUTH_TOKEN` optional Bearer token to require on requests
- `GUARDRAILS__ENABLED` whether to load model and serve checks, default `true`
- `GUARDRAILS__CONFIDENCE_THRESHOLD` decision threshold, default `0.7`
- `GUARDRAILS__BLOCK_ON_HIGH_RISK` included for parity; enforcement is in workflow
- `GUARDRAILS__HUGGINGFACE_CACHE_DIR` cache directory, default `/app/huggingface_cache`
- `GUARDRAILS__OFFLINE_MODE` use only cached model files if `true`

Example `config.yaml`:

```yaml
api:
  host: 0.0.0.0
  port: 8081
  auth_token:
  max_payload_bytes: 65536

guardrails:
  enabled: true
  confidence_threshold: 0.7
  block_on_high_risk: false
  huggingface_cache_dir: /app/huggingface_cache
  offline_mode: true
```

## Security

- To require authentication, set `SLM_GUARDRAIL_API__AUTH_TOKEN`. Clients must send `Authorization: Bearer <token>`.
- TLS termination should be handled by your ingress/proxy. The service uses system trust store when calling out (not required by default).

## Behavior and Error Handling

- When `guardrails.enabled` is `true` and the model is not ready, endpoints return `503 Service Unavailable`.
- When `guardrails.enabled` is `false`, endpoints return "safe" classifications with HTTP 200.
- Validation errors return `400`. Unexpected errors return `500` and the service fails open for individual checks.

## Resource Requirements

- CPU-backed model; memory usage depends on GLiNER model size. Cache the model under `GUARDRAILS__HUGGINGFACE_CACHE_DIR`.
- Set `GUARDRAILS__OFFLINE_MODE=true` in environments without internet access.

## Run Locally

- Python

```bash
uv run python main.py
```

- Docker

```bash
docker build -t slm-guardrail:local .
docker run --rm -p 8081:8081 -e SLM_GUARDRAIL_GUARDRAILS__OFFLINE_MODE=true slm-guardrail:local
```

## Development

- Install deps: `uv sync`
- Format and lint: `uv run ruff format . && uv run ruff check --fix .`
- Tests: `uv run pytest`
- OpenAPI docs at `/docs` when running locally

## Integration with zammad-ai-workflow

- In zammad-ai-workflow config, set:
  - `ZAMMAD_AI_GUARDRAILS__ENABLED=true`
  - `ZAMMAD_AI_GUARDRAILS__BASE_URL=http://slm-guardrail:8081/api/v1`
  - `ZAMMAD_AI_GUARDRAILS__REQUEST_TIMEOUT_SECONDS=3.0`
  - `ZAMMAD_AI_GUARDRAILS__AUTH_TOKEN=...` if auth is enabled
  - `ZAMMAD_AI_GUARDRAILS__VERIFY_TLS=true` when using HTTPS

## Troubleshooting

- `503 Model not ready`: Model failed to load or is initializing; check logs and cache path.
- Long first request: On first load, the model may be downloaded unless `offline_mode=true` with a populated cache.
- `401 Unauthorized`: Missing or incorrect `Authorization` header while `API__AUTH_TOKEN` is set.
