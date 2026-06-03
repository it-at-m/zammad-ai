"""Lightweight guardrail service using GLiNER for content safety."""

# ruff: noqa: E402
from asyncio import to_thread

from dotenv import load_dotenv
from truststore import inject_into_ssl

load_dotenv()
inject_into_ssl()

import os
from time import perf_counter

from gliner2 import GLiNER2
from prometheus_client import Counter, Histogram

from app.models.guardrails import GuardrailResponseResult, GuardrailResult
from app.settings.guardrails import GuardrailSettings
from app.utils.logging import getLogger

from .labels import JAILBREAK_TASK, PROMPT_TOXICITY_TASK, REFUSAL_LABELS, RESPONSE_TOXICITY_TASK, SAFETY_LABELS

logger = getLogger("zammad-ai.guardrails")

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
        """Initialize the GuardrailService.

        Parameters:
            settings (GuardrailSettings): Configuration for guardrail behavior.
        """
        self.settings: GuardrailSettings = settings
        self._model: GLiNER2 | None = None

        if self.settings.enabled:
            self._load_model()

    def _load_model(self) -> None:
        """Load or retrieve cached GLiNER model and tokenizer from HuggingFace."""
        try:
            os.environ["HF_HOME"] = self.settings.huggingface_cache_dir
            os.environ["TRANSFORMERS_CACHE"] = self.settings.huggingface_cache_dir
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            model_name = "fastino/gliguard-LLMGuardrails-300M"
            if not self.settings.offline_mode:
                model = GLiNER2.from_pretrained(
                    model_name,
                )
                model.save_pretrained(
                    os.path.join(self.settings.huggingface_cache_dir, model_name)
                )  # Ensure model is cached
            else:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                model = GLiNER2.from_pretrained(
                    os.path.join(self.settings.huggingface_cache_dir, model_name),
                    local_files_only=True,
                )

            model.to("cpu")
            self._model = model
            logger.info("Guardrail model loaded successfully.")
        except Exception:
            self._model = None
            logger.warning("Guardrail model could not be loaded; continuing without guardrails.", exc_info=True)

    async def evaluate(self, text: str) -> GuardrailResult:
        """Evaluate text for harmful content.

        Parameters:
            text (str): Input text to evaluate.

        Returns:
            GuardrailResult: Result containing risk level and detected entities.
        """
        if not self.settings.enabled or self._model is None:
            return GuardrailResult(prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[])

        # Return safe if text is empty
        if not text or not text.strip():
            logger.debug("Guardrail check skipped for empty text")
            return GuardrailResult(prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[])

        start_time = perf_counter()

        try:
            # Run classification tasks
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
            logger.debug(f"Guardrail raw classification result: {result}")
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

            # Fail open - allow processing if guardrails fail
            return GuardrailResult(prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[])

    async def evaluate_response(self, text: str, response: str) -> GuardrailResponseResult:
        """Evaluate generated response text for harmful content.

        Parameters:
            text (str): Original prompt text.
            response (str): Generated response text to evaluate.

        Returns:
            GuardrailResponseResult: Result containing risk level and detected entities.
        """
        if not self.settings.enabled or self._model is None:
            return GuardrailResponseResult(response_safety="safe", response_toxicity=[], response_refusal=[])

        # Return safe if response is empty
        if not response or not response.strip():
            logger.debug("Guardrail check skipped for empty response text")
            return GuardrailResponseResult(response_safety="safe", response_toxicity=[], response_refusal=[])

        start_time = perf_counter()

        try:
            combined_text = f"Prompt: {text}\nResponse: {response}"

            # Run classification tasks
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

            # Fail open - allow processing if guardrails fail
            return GuardrailResponseResult(response_safety="safe", response_toxicity=[], response_refusal=[])


_service: GuardrailService | None = None


def get_guardrail_service(settings: GuardrailSettings | None = None) -> GuardrailService:
    """Get or create the shared GuardrailService instance."""
    global _service
    if _service is None:
        if settings is None:
            settings = GuardrailSettings()
        _service = GuardrailService(settings)
    return _service
