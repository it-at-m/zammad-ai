# API Reference

Base path: `/api/v1`

## Authentication

If `api.api_key` is configured, requests must include:

```http
Authorization: Bearer <token>
```

If no API key is configured, the endpoints accept requests without a bearer token.

## Endpoints

### `GET /health`

Health check.

Response:

```json
{ "status": "healthy" }
```

### `GET /prompt_versions`

Returns the loaded prompt versions from triage and answer services.

### `POST /triage`

Classifies incoming text and selects a triage action.

Request:

```json
{ "text": "...", "session_id": "optional-uuid" }
```

Response fields:

- `triage.user_text`
- `triage.category`
- `triage.action`
- `triage.reasoning`
- `triage.confidence`
- `triage.extracted_values`
- `session_id`

### `POST /answer`

Generates an answer for a ticket.

Request:

```json
{
  "text": "...",
  "ticket_id": 12345,
  "category": "General Questions",
  "action": "AIAnswer",
  "session_id": "optional-uuid"
}
```

Response fields:

- `response`
- `documents` as `[{ "title": "...", "url": "..." }]`
- `auto_publish`

## Example

```bash
curl -X POST "http://localhost:8080/api/v1/triage" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"text":"Meine Frage..."}'
```
