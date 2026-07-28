slm-guardrails — Usage and Examples
=================================

This document shows example requests and guidance for interpreting guardrail results returned by slm-guardrails.

Endpoints
---------
- POST /api/v1/guardrails/prompt
  - Body: {"text": "...", "threshold": 0.7} (threshold optional)
  - Returns: GuardrailResult (JSON)

- POST /api/v1/guardrails/response
  - Body: {"text": "...", "response": "...", "threshold": 0.7} (threshold optional)
  - Returns: GuardrailResponseResult (JSON)

- GET /ready
  - Returns: {"model_ready": true|false}

Authentication
--------------
If configured, the service expects an Authorization header with a Bearer token:

  Authorization: Bearer \<token\>

Examples
--------
Curl (prompt):
```bash
  curl -X POST http://localhost:8081/api/v1/guardrails/prompt \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer secret" \
    -d '{"text": "How do I delete logs with personal data?", "threshold": 0.6}'
```

Curl (response):
```bash
  curl -X POST http://localhost:8081/api/v1/guardrails/response \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer secret" \
    -d '{"text": "User asks about deleting logs", "response": "You can remove them by...", "threshold": 0.6}'
```
Response schema (excerpt)
-------------------------
Both response models now include:

- overall safety label: `prompt_safety` / `response_safety` ("safe" / "unsafe")
- per-category labels: `prompt_toxicity` / `response_toxicity` (list of strings)
- jailbreak/refusal lists: `jailbreak_detection` / `response_refusal`
- `label_scores`: dict mapping label -> confidence (float). May be empty if model does not provide per-label scores.
- `raw_result`: raw model output (mirror of underlying classifier output)

Example successful response body (prompt)
```json
  {
    "prompt_safety": "unsafe",
    "prompt_toxicity": ["pii_exposure"],
    "jailbreak_detection": [],
    "label_scores": {"pii_exposure": 0.92},
    "raw_result": {"prompt_safety": "unsafe", "prompt_toxicity": ["pii_exposure"], "jailbreak_detection": []}
  }
```
How to interpret results (recommended)
-------------------------------------
The service returns structured data; the client should implement policy decisions. Suggested approach:

1. Check `model_ready` (/ready) before enforcing decisions.
2. Use `prompt_safety` / `response_safety` as a quick indicator.
3. Inspect `label_scores` for confidence values per label.
4. Apply deterministic decision rules locally. Example:

   - block if any label score >= 0.9
   - review if any label score >= 0.7
   - allow otherwise

5. Always record the raw_result and chosen action to your audit logs for traceability.

Python client example
---------------------
Minimal example showing a decision based on label_scores:
```python
  import requests

  def decide(result):
      scores = result.get("label_scores", {})
      if not scores:
          return "allow"
      top = max(scores.values())
      if top >= 0.9:
          return "block"
      if top >= 0.7:
          return "review"
      return "allow"

  resp = requests.post(
      "http://localhost:8081/api/v1/guardrails/prompt",
      json={"text": "..."},
      headers={"Authorization": "Bearer secret"},
  )
  data = resp.json()
  action = decide(data)
  print("Action:", action)
```
Metrics
-------
Exposed metrics (Prometheus) are mounted at /metrics. Useful metrics:

- zammad_ai_guardrail_checks_total (labels: outcome, type)
- zammad_ai_guardrail_check_duration_seconds (label: type)

Notes
-----
- The service returns the raw model output to preserve transparency for clients.
- Per-request threshold is supported — it overrides the configured default for that single request and does not mutate settings.
- The service will fail to start if the model cannot be initialized (so orchestrators can detect the condition).

If you want a recommended_action computed by the service (in addition to the raw result), open an issue or ask and I will add an optional `recommended_action` field that follows a deterministic rule-set but leaves final decisions to the caller.
