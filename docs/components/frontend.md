# Frontend / Developer UI

The project includes an optional Gradio-based frontend module for local developer workflows.

## Scope

- This UI is mounted in the FastAPI runtime at `/` when enabled.
- It is intended for development and troubleshooting, not as a production UI platform.
- It is separate from this VitePress documentation site.

## Runtime Integration

Frontend code lives under `zammad-ai-workflow/app/frontend` and is mounted through backend startup wiring in `zammad-ai-workflow/app/api/backend.py`.

When `frontend.enabled` is true:

- Gradio Blocks UI is mounted at `/`.
- Frontend calls API endpoints under `/api/v1/triage` and `/api/v1/answer`.
- Basic auth is enabled and required.

When `frontend.enabled` is false and mode is `development`:

- `/` redirects to `/api/docs` (OpenAPI docs).

## Configuration

Frontend settings are configured under `frontend` in `zammad-ai-workflow/config.yaml`.

```yaml
frontend:
  enabled: true
  request_timeout_seconds: 300.0
  auth_username: "admin"
  auth_password: "change-me"
```

Environment variable overrides follow the usual nested settings pattern, e.g.:

- `ZAMMAD_AI_FRONTEND__ENABLED`
- `ZAMMAD_AI_FRONTEND__AUTH_USERNAME`
- `ZAMMAD_AI_FRONTEND__AUTH_PASSWORD`
