"""HTTP client-based GuardrailService.

This replaces the previous in-process GLiNER implementation. When enabled,
all checks call the configured slm-guardrail FastAPI service. When disabled,
the client returns safe results immediately (skips guardrails).
"""

from __future__ import annotations

from typing import Any, Final

import httpx
from dotenv import load_dotenv
from httpx._models import Response
from truststore import inject_into_ssl

from app.models.guardrails import GuardrailResponseResult, GuardrailResult
from app.settings.guardrails import GuardrailSettings
from app.utils.logging import getLogger

load_dotenv()
inject_into_ssl()


logger = getLogger("zammad-ai.guardrails.http")


SAFE_PROMPT_RESULT: Final[GuardrailResult] = GuardrailResult(
    prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[]
)
SAFE_RESPONSE_RESULT: Final[GuardrailResponseResult] = GuardrailResponseResult(
    response_safety="safe", response_toxicity=[], response_refusal=[]
)


class GuardrailService:
    """Guardrail client that talks to the external slm-guardrail HTTP service."""

    def __init__(self, settings: GuardrailSettings) -> None:
        """Construct a client with base URL, timeout and optional auth header."""
        self.settings = settings
        self._base_url = settings.base_url.rstrip("/")
        self._timeout = settings.request_timeout_seconds
        self._auth_header = (
            {"Authorization": f"Bearer {settings.auth_token}"}
            if settings.auth_token
            else {}
        )

        # Create a shared AsyncClient; FastAPI/uvicorn lifecycle will span calls.
        # We rely on truststore's global injection for TLS roots.
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            verify=settings.verify_tls,
            headers={"Content-Type": "application/json", **self._auth_header},
            follow_redirects=True,
        )

    async def evaluate(self, text: str) -> GuardrailResult:
        """Evaluate user input text via remote guardrail service or skip when disabled."""
        if not self.settings.enabled:
            return SAFE_PROMPT_RESULT

        # Skip empty text to avoid unnecessary calls
        if not text or not text.strip():
            logger.debug("Guardrail skipped for empty text")
            return SAFE_PROMPT_RESULT

        url = f"{self._base_url}/guardrails/prompt"
        payload = {"text": text, "threshold": self.settings.confidence_threshold}
        try:
            resp: Response = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
            # Coerce using our Pydantic model to guard against schema drift
            return GuardrailResult(**data)
        except Exception:
            # Fail-open on any error
            logger.error("Remote guardrail evaluate failed.", exc_info=True)
            return SAFE_PROMPT_RESULT

    async def evaluate_response(self, text: str, response: str) -> GuardrailResponseResult:
        """Evaluate generated response via remote guardrail service or skip when disabled."""
        if not self.settings.enabled:
            return SAFE_RESPONSE_RESULT

        if not response or not response.strip():
            logger.debug("Guardrail skipped for empty response")
            return SAFE_RESPONSE_RESULT

        url = f"{self._base_url}/guardrails/response"
        payload = {
            "text": text,
            "response": response,
            "threshold": self.settings.confidence_threshold,
        }
        try:
            resp: Response = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
            return GuardrailResponseResult(**data)
        except Exception:
            logger.error("Remote guardrail evaluate_response failed.", exc_info=True)
            return SAFE_RESPONSE_RESULT


_service: GuardrailService | None = None


def get_guardrail_service(settings: GuardrailSettings | None = None) -> GuardrailService:
    """Return a singleton GuardrailService instance backed by HTTP client."""
    global _service
    if _service is None:
        if settings is None:
            from app.settings import get_settings

            settings = get_settings().guardrails
        _service = GuardrailService(settings)
    return _service
