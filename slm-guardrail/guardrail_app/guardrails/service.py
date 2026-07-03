"""Guardrail service for content safety backends (GLiNER2 and GLiClass)."""

import asyncio
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any

from guardrail_app.models.guardrails import GuardrailResponseResult, GuardrailResult
from guardrail_app.settings.settings import GuardrailSettings, ModelConfig
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
    labelnames=("type",),
)


class _GLiClassGuardrailAdapter:
    """Adapter that normalizes GLiClass outputs into the service's schema."""

    def __init__(self, model_name: str, cache_dir: str, offline: bool) -> None:
        try:
            gliclass_module = importlib.import_module("gliclass")
            GLiClassModel = getattr(gliclass_module, "GLiClassModel")
            ZeroShotClassificationPipeline = getattr(gliclass_module, "ZeroShotClassificationPipeline")
            from transformers import AutoTokenizer
        except ImportError as e:
            logger.error("gliclass is required but not installed. Install with `pip install gliclass`.", exc_info=True)
            raise RuntimeError("Missing dependency: gliclass") from e

        load_kwargs: dict[str, Any] = {"cache_dir": cache_dir, "local_files_only": offline}
        model = GLiClassModel.from_pretrained(model_name, **load_kwargs)
        tokenizer = AutoTokenizer.from_pretrained(model_name, **load_kwargs)
        self._binary_pipeline = ZeroShotClassificationPipeline(
            model=model,
            tokenizer=tokenizer,
            classification_type="single-label",
            device="cpu",
        )
        self._multi_label_pipeline = ZeroShotClassificationPipeline(
            model=model,
            tokenizer=tokenizer,
            classification_type="multi-label",
            device="cpu",
        )

    def _score_map(self, text: str, labels: list[str], *, threshold: float, single_label: bool) -> dict[str, float]:
        pipeline = self._binary_pipeline if single_label else self._multi_label_pipeline
        try:
            output = pipeline(text, labels, threshold=threshold, return_hierarchical=True)
        except Exception as e:
            logger.error("GLiClass pipeline invocation failed.", exc_info=True)
            # Return zeros so upstream can still operate
            return {label: 0.0 for label in labels}

        if not output:
            return {label: 0.0 for label in labels}

        # Pipeline outputs may vary by version. Try to extract a mapping of label->score.
        try:
            # common shape: a list where the first element is a dict mapping label->score
            scores = output[0]
            if isinstance(scores, dict):
                return {str(label): float(score) for label, score in scores.items()}

            # another shape: list of (label, score) pairs or list of objects
            if isinstance(scores, (list, tuple)):
                mapping: dict[str, float] = {}
                for item in scores:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        mapping[str(item[0])] = float(item[1])
                    elif isinstance(item, dict) and "label" in item and "score" in item:
                        mapping[str(item["label"])] = float(item["score"])
                if mapping:
                    return mapping

        except Exception:
            logger.debug("Unexpected GLiClass pipeline output format", exc_info=True)

        # Fallback: return zeros
        return {label: 0.0 for label in labels}

    def classify_text(self, text: str, tasks: dict[str, Any], threshold: float = 0.7) -> dict[str, Any]:
        label_scores: dict[str, float] = {}
        result: dict[str, Any] = {}

        for task_name, task_spec in tasks.items():
            labels = task_spec.get("labels", task_spec) if isinstance(task_spec, dict) else task_spec
            if not isinstance(labels, list):
                labels = list(labels)

            task_threshold = threshold
            if isinstance(task_spec, dict) and task_spec.get("cls_threshold") is not None:
                task_threshold = float(task_spec["cls_threshold"])

            if task_name in {"prompt_safety", "response_safety"}:
                scores = self._score_map(text, labels, threshold=task_threshold, single_label=True)
                result[task_name] = max(scores, key=lambda label: scores[label]) if scores else labels[0]
            else:
                scores = self._score_map(text, labels, threshold=task_threshold, single_label=False)
                result[task_name] = [label for label in labels if scores.get(label, 0.0) >= task_threshold]

            for label, score in scores.items():
                label_scores[f"{task_name}.{label}"] = score

        result["label_scores"] = label_scores
        return result


class GuardrailService:
    """Service for evaluating content safety using model-specific adapters."""

    def __init__(self, settings: GuardrailSettings) -> None:
        """Initialize the service with guardrail settings and load the model."""
        self.settings: GuardrailSettings = settings
        self._models: dict[str, Any] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        # per-model executors to avoid relying on the loop default executor
        self._executors: dict[str, ThreadPoolExecutor] = {}
        self._load_models()

    def _load_models(self) -> None:
        """Load all models configured in settings.guardrails.models.

        Individual model failures are logged and skipped so one unsupported
        optional model does not prevent the service from starting.
        """
        failures = 0
        for model_id, cfg in self.settings.models.items():
            try:
                self._load_model(model_id, cfg)
            except Exception:
                logger.error("Failed to load model '%s'", model_id, exc_info=True)
                failures += 1

        if not self._models:
            raise RuntimeError("No guardrail models could be loaded")

        if failures:
            logger.warning("Started with %s guardrail model(s) unavailable.", failures)

    def _load_model(self, model_id: str, cfg: ModelConfig) -> None:
        """Load a single model instance and register it under model_id."""
        cache_dir = cfg.huggingface_cache_dir or self.settings.huggingface_cache_dir
        offline = cfg.offline_mode if cfg.offline_mode is not None else self.settings.offline_mode
        max_conc = cfg.max_concurrency if cfg.max_concurrency is not None else self.settings.max_concurrency
        model_name = cfg.hf_model_name
        backend = self._infer_backend(model_id, model_name)
        try:
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except Exception:
                logger.debug("Could not ensure huggingface cache dir exists for model %s", model_id)

            if backend == "gliclass":
                model = _GLiClassGuardrailAdapter(model_name, cache_dir, offline)
            else:
                # Import GLiNER2 only when needed so gliclass-only deployments don't require it
                try:
                    from gliner2 import GLiNER2  # local import
                except ImportError as e:
                    logger.error(
                        "gliner2 is required for model '%s' but not installed. Install with `pip install gliner2`.",
                        model_id,
                        exc_info=True,
                    )
                    raise RuntimeError("Missing dependency: gliner2") from e

                if not offline:
                    model = GLiNER2.from_pretrained(model_name)
                    try:
                        model.save_pretrained(os.path.join(cache_dir, model_name))
                    except Exception:
                        logger.debug("Could not save pretrained model to cache for %s", model_id)
                else:
                    model = GLiNER2.from_pretrained(os.path.join(cache_dir, model_name), local_files_only=True)
                model.to("cpu")

            self._models[model_id] = model
            self._semaphores[model_id] = asyncio.Semaphore(max_conc)
            # create a dedicated executor sized to the model's concurrency
            exec_workers = max_conc if isinstance(max_conc, int) and max_conc > 0 else 1
            self._executors[model_id] = ThreadPoolExecutor(max_workers=exec_workers, thread_name_prefix=f"guardrail-{model_id}")
            logger.info("Guardrail model '%s' loaded successfully.", model_id)
        except Exception:
            logger.error("Guardrail model '%s' could not be loaded", model_id, exc_info=True)
            raise

    def _infer_backend(self, model_id: str, model_name: str) -> str:
        """Infer the loading backend from the configured model name."""
        normalized_name = model_name.lower()
        if model_id.lower() == "opir" or "gliclass" in normalized_name or "opir" in normalized_name:
            return "gliclass"
        return "gliner2"

    def has_model(self, model_id: str) -> bool:
        """Return True if the model_id is known and a model instance is loaded."""
        return model_id in self._models and self._models.get(model_id) is not None

    async def evaluate(self, text: str, threshold: float | None, model_id: str | None = None) -> GuardrailResult:
        """Classify input text for safety, toxicity, and jailbreak indicators."""
        mid = model_id or self.settings.default_model
        if mid not in self._models:
            raise RuntimeError(f"Model '{mid}' is not loaded.")

        model = self._models[mid]
        sem = self._semaphores[mid]

        if not text or not text.strip():
            logger.debug("Guardrail check skipped for empty text")
            return GuardrailResult(prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[])

        start_time = perf_counter()
        async with sem:
            try:
                loop = asyncio.get_running_loop()
                raw = await loop.run_in_executor(
                    self._executors[mid],
                    model.classify_text,
                    text,
                    {
                        "prompt_safety": SAFETY_LABELS,
                        "prompt_toxicity": PROMPT_TOXICITY_TASK,
                        "jailbreak_detection": JAILBREAK_TASK,
                    },
                    threshold if threshold is not None else self.settings.confidence_threshold,
                )
                rdict = dict(raw)
                rdict.setdefault("label_scores", {})
                rdict["raw_result"] = dict(raw)
                result = GuardrailResult(**rdict)
                outcome = result.prompt_safety if result.prompt_safety in set(SAFETY_LABELS) else "other"
                GUARDRAIL_CHECKS_TOTAL.labels(outcome=outcome, type="prompt").inc()
                duration = perf_counter() - start_time
                GUARDRAIL_CHECK_DURATION_SECONDS.labels(type="prompt").observe(duration)
                logger.info(
                    f"Guardrail check completed: safety={result.prompt_safety}, toxicity={result.prompt_toxicity}, jailbreak={result.jailbreak_detection}, duration={duration:.2f}s"
                )
                return result
            except Exception:
                logger.error("Guardrail evaluation failed.", exc_info=True)
                GUARDRAIL_CHECKS_TOTAL.labels(outcome="error", type="prompt").inc()
                raise

    async def evaluate_response(
        self, text: str, response: str, threshold: float | None, model_id: str | None = None
    ) -> GuardrailResponseResult:
        """Classify a generated response (with prompt context) for safety and refusal."""
        mid = model_id or self.settings.default_model
        if mid not in self._models:
            raise RuntimeError(f"Model '{mid}' is not loaded.")

        model = self._models[mid]
        sem = self._semaphores[mid]

        if not response or not response.strip():
            logger.debug("Guardrail check skipped for empty response text")
            return GuardrailResponseResult(response_safety="safe", response_toxicity=[], response_refusal=[])

        start_time = perf_counter()
        async with sem:
            try:
                combined_text = f"Prompt: {text}\nResponse: {response}"
                loop = asyncio.get_running_loop()
                raw = await loop.run_in_executor(
                    self._executors[mid],
                    model.classify_text,
                    combined_text,
                    {
                        "response_safety": SAFETY_LABELS,
                        "response_toxicity": RESPONSE_TOXICITY_TASK,
                        "response_refusal": REFUSAL_LABELS,
                    },
                    threshold if threshold is not None else self.settings.confidence_threshold,
                )
                rdict = dict(raw)
                rdict.setdefault("label_scores", {})
                rdict["raw_result"] = dict(raw)
                result = GuardrailResponseResult(**rdict)
                outcome = result.response_safety if result.response_safety in set(SAFETY_LABELS) else "other"
                GUARDRAIL_CHECKS_TOTAL.labels(outcome=outcome, type="response").inc()
                duration = perf_counter() - start_time
                GUARDRAIL_CHECK_DURATION_SECONDS.labels(type="response").observe(duration)
                logger.info(
                    f"Guardrail check for response completed: safety={result.response_safety}, toxicity={result.response_toxicity}, refusal={result.response_refusal}, duration={duration:.2f}s"
                )
                return result
            except Exception:
                logger.error("Guardrail evaluation for response failed.", exc_info=True)
                GUARDRAIL_CHECKS_TOTAL.labels(outcome="error", type="response").inc()
                raise

    async def close(self) -> None:
        """Shutdown per-model executors and clear loaded models.

        This should be called from application shutdown to free threadpool resources.
        """
        for model_id, executor in list(self._executors.items()):
            try:
                executor.shutdown(wait=False)
            except Exception:
                logger.debug("Failed to shutdown executor for model %s", model_id, exc_info=True)
        self._executors.clear()
        # Drop model references to allow GC
        self._models.clear()
        self._semaphores.clear()
