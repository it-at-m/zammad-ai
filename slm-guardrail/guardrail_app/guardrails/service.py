"""Guardrail service using GLiNER for content safety (server-side)."""

# ruff: noqa: E402
from asyncio import to_thread

from dotenv import load_dotenv
from truststore import inject_into_ssl

load_dotenv()
inject_into_ssl()

import os
from time import perf_counter
from typing import Any

from guardrail_app.models.guardrails import GuardrailResponseResult, GuardrailResult
from guardrail_app.settings.settings import GuardrailSettings
from guardrail_app.utils.logging import getLogger
from prometheus_client import Counter, Histogram

from .labels import JAILBREAK_TASK, PROMPT_TOXICITY_TASK, REFUSAL_LABELS, RESPONSE_TOXICITY_TASK, SAFETY_LABELS

logger = getLogger("slm-guardrail")

GUARDRAIL_CHECKS_TOTAL = Counter(
    name="zammad_ai_guardrail_checks_total",
    documentation="Total guardrail checks performed.",
    labelnames=("outcome", "type"),
)

GUARDRAIL_CHECK_DURATION_SECONDS = Histogram(
    name="zammad_ai_guardrail_check_duration_seconds",
    documentation="Duration of guardrail checks in seconds.",
)


class GuardrailService:
    """Service for evaluating content safety using GLiNER entity recognition."""

    def __init__(self, settings: GuardrailSettings) -> None:
        """Initialize the service with guardrail settings and load the model if enabled."""
        self.settings: GuardrailSettings = settings
        # Avoid importing heavy ML libs at import time; load lazily in _load_model
        # Use Any to avoid runtime import solely for typing
        self._model: Any | None = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            # Import GLiNER model lazily to prevent global side effects during testing
            from gliner2 import GLiNER2  # local import to avoid torch import at module import time

            os.environ["HF_HOME"] = self.settings.huggingface_cache_dir
            os.environ["HF_HUB_CACHE"] = self.settings.huggingface_cache_dir
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            model_name = "fastino/gliguard-LLMGuardrails-300M"
            if not self.settings.offline_mode:
                model = GLiNER2.from_pretrained(model_name)
                model.save_pretrained(os.path.join(self.settings.huggingface_cache_dir, model_name))
            else:
                model = GLiNER2.from_pretrained(
                    os.path.join(self.settings.huggingface_cache_dir, model_name),
                    local_files_only=True,
                )
            model.to("cpu")
            self._model = model
            logger.info("Guardrail model loaded successfully.")
        except Exception as e:
            self._model = None
            logger.error("Guardrail model could not be loaded", exc_info=True)
            raise RuntimeError("Guardrail model failed to load.") from e

    async def evaluate(self, text: str) -> GuardrailResult:
        """Classify input text for safety, toxicity, and jailbreak indicators.

        Returns a safe result if the model is unavailable or an error occurs.
        """
        if self._model is None:
            raise RuntimeError("Guardrail model is not loaded.")

        if not text or not text.strip():
            logger.debug("Guardrail check skipped for empty text")
            return GuardrailResult(prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[])

        start_time = perf_counter()
        try:
            result = await to_thread(
                self._model.classify_text,
                text,
                {
                    "prompt_safety": SAFETY_LABELS,
                    "prompt_toxicity": PROMPT_TOXICITY_TASK,
                    "jailbreak_detection": JAILBREAK_TASK,
                },
                threshold=self.settings.confidence_threshold,
            )
            result = GuardrailResult(**result)
            GUARDRAIL_CHECKS_TOTAL.labels(outcome=result.prompt_safety, type="prompt").inc()
            duration = perf_counter() - start_time
            GUARDRAIL_CHECK_DURATION_SECONDS.observe(duration)
            logger.info(
                f"Guardrail check completed: safety={result.prompt_safety}, toxicity={result.prompt_toxicity}, jailbreak={result.jailbreak_detection}, duration={duration:.2f}s"
            )
            return result
        except Exception:
            logger.error("Guardrail evaluation failed.", exc_info=True)
            GUARDRAIL_CHECKS_TOTAL.labels(outcome="error", type="prompt").inc()
            return GuardrailResult(prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[])

    async def evaluate_response(self, text: str, response: str) -> GuardrailResponseResult:
        """Classify a generated response (with prompt context) for safety and refusal."""
        if self._model is None:
            raise RuntimeError("Guardrail model is not loaded.")

        if not response or not response.strip():
            logger.debug("Guardrail check skipped for empty response text")
            return GuardrailResponseResult(response_safety="safe", response_toxicity=[], response_refusal=[])

        start_time = perf_counter()
        try:
            combined_text = f"Prompt: {text}\nResponse: {response}"
            result = await to_thread(
                self._model.classify_text,
                combined_text,
                {
                    "response_safety": SAFETY_LABELS,
                    "response_toxicity": RESPONSE_TOXICITY_TASK,
                    "response_refusal": REFUSAL_LABELS,
                },
                threshold=self.settings.confidence_threshold,
            )
            result = GuardrailResponseResult(**result)
            GUARDRAIL_CHECKS_TOTAL.labels(outcome=result.response_safety, type="response").inc()
            duration = perf_counter() - start_time
            GUARDRAIL_CHECK_DURATION_SECONDS.observe(duration)
            logger.info(
                f"Guardrail check for response completed: safety={result.response_safety}, toxicity={result.response_toxicity}, refusal={result.response_refusal}, duration={duration:.2f}s"
            )
            return result
        except Exception:
            logger.error("Guardrail evaluation for response failed.", exc_info=True)
            GUARDRAIL_CHECKS_TOTAL.labels(outcome="error", type="response").inc()
            return GuardrailResponseResult(response_safety="safe", response_toxicity=[], response_refusal=[])
