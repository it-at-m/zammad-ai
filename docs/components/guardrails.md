# Guardrails Service

`slm-guardrails` is the external content-safety service used by `zammad-ai-workflow`.

## Purpose

It evaluates user prompts and generated responses before the workflow continues.

## Endpoints

- `GET /healthz` for liveness
- `GET /ready` for model readiness
- `GET /metrics` for Prometheus metrics
- `POST /api/v1/guardrails/prompt`
- `POST /api/v1/guardrails/response`
- `GET /api/v1/models`

## Request Flow

- Requests are optionally protected by a bearer token.
- Empty text is treated as safe.
- The service loads guardrail models on startup and fails fast if none can be loaded.
- The workflow client sends the configured model id and confidence threshold.

## Configuration

The service uses `SLM_GUARDRAIL_` as the environment prefix.

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

## Response Shape

Prompt evaluation returns:

- `prompt_safety`
- `prompt_toxicity`
- `jailbreak_detection`

Response evaluation returns:

- `response_safety`
- `response_toxicity`
- `response_refusal`

## Integration

The workflow service uses `app/guardrails/http_client.py` to call this service when `guardrails.enabled` is true.
