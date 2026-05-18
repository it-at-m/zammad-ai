## API Reference

This document describes the HTTP API for the Zammad-AI service (v1).

**Base path:** `/api/v1`

**Authentication**

- The API uses a simple token-based authentication. Provide the token using the `Authorization` header with the `Bearer` scheme:
  - Header name: `Authorization`
  - Format: `Authorization: Bearer <token>`

  If no API key is configured in the server settings, authentication is disabled and requests are accepted without a header.

**Endpoints**

- `POST /api/v1/triage`
  - Description: Classify ticket text and determine an action.
  - Request JSON: `{ "text": "...", "session_id": "optional-uuid" }`
  - Response JSON (example):
    ```json
    {
      "triage": {
        "user_text": "...",
        "category": { "name": "Fragen" },
        "action": { "name": "AI_Answer" },
        "reasoning": "...",
        "confidence": 0.87
      },
      "session_id": "..."
    }
    ```

- `POST /api/v1/answer`
  - Description: Request an AI-generated answer for a ticket when the action requires it.
  - Request JSON: `{ "text": "...", "category": "...", "action": "...", "session_id": "..." }`
  - Response JSON (example):
    ```json
    {
      "response": "Generated answer text...",
      "documents": [{ "id": "...", "source": "..." }],
      "auto_publish": false
    }
    ```

**Examples (curl)**

- Triage:
```bash
  curl -X POST "http://localhost:8080/api/v1/triage" \
   -H "Content-Type: application/json" \
   -H "Authorization: Bearer <token>" \
   -d '{"text": "Meine Frage..."}'
```
- Answer:
```bash
  curl -X POST "http://localhost:8080/api/v1/answer" \
   -H "Content-Type: application/json" \
   -H "Authorization: Bearer <token>" \
   -d '{"text": "...", "category": "Fragen", "action": "AI_Answer", "session_id": "..."}'
```
