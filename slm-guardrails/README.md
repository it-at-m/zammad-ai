# slm-guardrails

FastAPI service that evaluates prompts and generated responses for the Zammad-AI workflow.

## Features

- `GET /healthz`
- `GET /ready`
- `GET /metrics`
- `GET /api/v1/models`
- `POST /api/v1/guardrails/prompt`
- `POST /api/v1/guardrails/response`
- Optional bearer authentication
- Model cache support and offline mode (The service have to run in an environment with internet access at least once to download the model weights)

## API

### Prompt evaluation

`POST /api/v1/guardrails/prompt`

Request:

```json
{ "text": "string", "model": "default", "threshold": 0.7 }
```

Response:

```json
{ "prompt_safety": "safe", "prompt_toxicity": [], "jailbreak_detection": [] }
```

### Response evaluation

`POST /api/v1/guardrails/response`

Request:

```json
{ "text": "string", "response": "string", "model": "default", "threshold": 0.7 }
```

Response:

```json
{ "response_safety": "safe", "response_toxicity": [], "response_refusal": [] }
```

## Configuration

The service uses the `SLM_GUARDRAIL_` environment prefix.

Relevant settings:

- `api.host`
- `api.port`
- `api.auth_token`
- `api.max_input_length`
- `guardrails.confidence_threshold`
- `guardrails.huggingface_cache_dir`
- `guardrails.offline_mode`
- `guardrails.max_concurrency`
- `guardrails.default_model`
- `guardrails.models`

Example `config.yaml`:

```yaml
api:
  host: 0.0.0.0
  port: 8081
  auth_token:
  max_input_length: 10000

guardrails:
  confidence_threshold: 0.7
  huggingface_cache_dir: /app/huggingface_cache
  offline_mode: true
  max_concurrency: 4
  default_model: default
  models:
    default:
      hf_model_name: fastino/gliguard-LLMGuardrails-300M
```

## Workflow integration

Set the workflow guardrails client to point here:

- `ZAMMAD_AI_GUARDRAILS__ENABLED=true`
- `ZAMMAD_AI_GUARDRAILS__BASE_URL=http://slm-guardrails:8081`
- `ZAMMAD_AI_GUARDRAILS__REQUEST_TIMEOUT_SECONDS=3.0`
- `ZAMMAD_AI_GUARDRAILS__AUTH_TOKEN=...` when auth is enabled

## Run

```bash
uv run python main.py
```
