"""HTTP client-based GuardrailService."""

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
    """Guardrail client that talks to the external slm-guardrails HTTP service."""

    def __init__(self, settings: GuardrailSettings) -> None:
        """Construct a client with base URL, timeout and optional auth header."""
        self.settings = settings
        self._base_url = str(settings.base_url).rstrip("/")
        self._timeout = settings.request_timeout_seconds
        self._auth_header = {"Authorization": f"Bearer {settings.auth_token}"} if settings.auth_token else {}

        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            verify=settings.verify_tls,
            headers={"Content-Type": "application/json", **self._auth_header},
            follow_redirects=True,
        )
        self._closed = False

    async def evaluate(self, text: str) -> GuardrailResult | None:
        """Evaluate user input text via remote guardrail service or skip when disabled."""
        if not self.settings.enabled:
            return None

        # Skip empty text to avoid unnecessary calls
        if not text or not text.strip():
            logger.debug("Guardrail skipped for empty text")
            return SAFE_PROMPT_RESULT

        url = f"{self._base_url}/api/v1/guardrails/prompt"
        payload = {
            "text": text,
            "threshold": self.settings.confidence_threshold,
            "model": self.settings.model,
        }
        try:
            resp: Response = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
            # Coerce using our Pydantic model to guard against schema drift
            return GuardrailResult(**data)
        except Exception:
            # Fail-open on any error
            logger.error("Remote guardrail evaluate failed.", exc_info=True)
            return None

    async def close(self) -> None:
        """Close the underlying HTTPX client."""
        if self._closed:
            return

        await self._client.aclose()
        self._closed = True

    async def evaluate_response(self, text: str, response: str) -> GuardrailResponseResult | None:
        """Evaluate generated response via remote guardrail service or skip when disabled."""
        if not self.settings.enabled:
            return None

        if not response or not response.strip():
            logger.debug("Guardrail skipped for empty response")
            return SAFE_RESPONSE_RESULT

        url = f"{self._base_url}/api/v1/guardrails/response"
        payload = {
            "text": text,
            "response": response,
            "threshold": self.settings.confidence_threshold,
            "model": self.settings.model,
        }
        try:
            resp: Response = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
            return GuardrailResponseResult(**data)
        except Exception:
            logger.error("Remote guardrail evaluate_response failed.", exc_info=True)
            return None


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


def reset_guardrail_service() -> None:
    """Clear the shared GuardrailService singleton so it can be recreated."""
    global _service
    _service = None
