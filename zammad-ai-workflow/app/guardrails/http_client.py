"""HTTP client-based GuardrailService."""

from __future__ import annotations

from logging import getLogger
from typing import Any, Final

import httpx
from dotenv import load_dotenv
from httpx._models import Response
from truststore import inject_into_ssl

from app.errors import GuardrailEvaluationError
from app.models.guardrails import GuardrailResponseResult, GuardrailResult
from app.settings.guardrails import GuardrailSettings

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

    async def evaluate(
        self, text: str, toxicity_labels: list[str] | None = None, jailbreak_labels: list[str] | None = None
    ) -> bool:
        """Evaluate user input text via remote guardrail service or skip when disabled."""
        if not self.settings.enabled:
            return True

        # Skip empty text to avoid unnecessary calls
        if not text or not text.strip():
            logger.debug("Guardrail skipped for empty text")
            return True

        url = f"{self._base_url}/api/v1/guardrails/prompt"
        payload = {
            "text": text,
            "threshold": self.settings.confidence_threshold,
            "model": self.settings.model,
            "toxicity_labels": toxicity_labels,
            "jailbreak_labels": jailbreak_labels,
        }
        try:
            resp: Response = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
            # Coerce using our Pydantic model to guard against schema drift
            result = GuardrailResult(**data)
            return is_guardrail_safe(result)
        except Exception as e:
            # Fail-open on any error
            logger.error("Remote guardrail evaluate failed.", exc_info=True)
            raise GuardrailEvaluationError("Remote guardrail evaluate failed") from e

    async def close(self) -> None:
        """Close the underlying HTTPX client."""
        if self._closed:
            return

        await self._client.aclose()
        self._closed = True

    async def evaluate_response(self, text: str, response: str, toxicity_labels: list[str] | None = None) -> bool:
        """Evaluate generated response via remote guardrail service or skip when disabled."""
        if not self.settings.enabled:
            return True

        if not response or not response.strip():
            logger.debug("Guardrail skipped for empty response")
            return True

        url = f"{self._base_url}/api/v1/guardrails/response"
        payload = {
            "text": text,
            "response": response,
            "threshold": self.settings.confidence_threshold,
            "model": self.settings.model,
            "toxicity_labels": toxicity_labels,
        }
        try:
            resp: Response = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
            return is_guardrail_safe(GuardrailResponseResult(**data))
        except Exception as e:
            logger.error("Remote guardrail evaluate_response failed.", exc_info=True)
            raise GuardrailEvaluationError("Remote guardrail evaluate_response failed") from e


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


def is_guardrail_safe(guardrail_result: GuardrailResult | GuardrailResponseResult | None) -> bool:
    """Determine if the guardrail result is safe or not."""
    if guardrail_result is None:
        return False
    elif isinstance(guardrail_result, GuardrailResult):
        if guardrail_result.prompt_safety == "safe":
            return True
        if (
            len(guardrail_result.jailbreak_detection) == 1 and guardrail_result.jailbreak_detection[0] == "benign"
        ) and (len(guardrail_result.prompt_toxicity) == 1 and guardrail_result.prompt_toxicity[0] == "benign"):
            return True
    elif isinstance(guardrail_result, GuardrailResponseResult):
        if guardrail_result.response_safety == "safe":
            return True
        if len(guardrail_result.response_toxicity) == 1 and guardrail_result.response_toxicity[0] == "benign":
            return True
    return False
