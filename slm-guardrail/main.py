"""slm-guardrail FastAPI entrypoint with endpoints and metrics."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from guardrail_app.guardrails.service import GuardrailService
from guardrail_app.models.guardrails import GuardrailResponseResult, GuardrailResult
from guardrail_app.settings.settings import ServiceSettings, get_settings
from guardrail_app.utils.logging import getLogger
from prometheus_client import make_asgi_app

logger = getLogger("slm-guardrail")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: initialize and gracefully shutdown the service.

    Replaces deprecated on_event startup/shutdown hooks.
    """
    global _service
    settings = get_settings()
    try:
        _service = GuardrailService(settings.guardrails)
        logger.info("slm-guardrail started")
    except Exception:
        _service = None
        logger.error("Failed to initialize guardrail model on startup.", exc_info=True)
    # Yield control to serve requests
    try:
        yield
    finally:
        logger.info("slm-guardrail shutting down")


app = FastAPI(title="slm-guardrail", version="0.1.0", lifespan=lifespan)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

_service: GuardrailService | None = None


def _get_service(settings: ServiceSettings = Depends(get_settings)) -> GuardrailService | None:
    return _service


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "ok"}


def _auth_check(request: Request, settings: ServiceSettings) -> None:
    token = settings.api.auth_token
    if token:
        header = request.headers.get("authorization", "")
        if header != f"Bearer {token}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.post("/api/v1/guardrails/prompt", response_model=GuardrailResult)
async def evaluate_prompt(
    request: Request,
    payload: dict,
    settings: ServiceSettings = Depends(get_settings),
    service: GuardrailService | None = Depends(_get_service),
) -> GuardrailResult:
    """Evaluate a user prompt text for safety via the model service."""
    _auth_check(request, settings)
    text = str(payload.get("text", ""))
    threshold = payload.get("threshold")
    if threshold is not None:
        try:
            settings.guardrails.confidence_threshold = float(threshold)
        except Exception:
            pass  # ignore invalid override

    if service is None and settings.guardrails.enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Model not ready")
    if service is None:
        # Disabled -> safe
        return GuardrailResult(prompt_safety="safe", prompt_toxicity=[], jailbreak_detection=[])

    return await service.evaluate(text)


@app.post("/api/v1/guardrails/response", response_model=GuardrailResponseResult)
async def evaluate_response(
    request: Request,
    payload: dict,
    settings: ServiceSettings = Depends(get_settings),
    service: GuardrailService | None = Depends(_get_service),
) -> GuardrailResponseResult:
    """Evaluate a generated response (with prompt context) for safety."""
    _auth_check(request, settings)
    text = str(payload.get("text", ""))
    response_text = str(payload.get("response", ""))
    threshold = payload.get("threshold")
    if threshold is not None:
        try:
            settings.guardrails.confidence_threshold = float(threshold)
        except Exception:
            pass

    if service is None and settings.guardrails.enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Model not ready")
    if service is None:
        return GuardrailResponseResult(response_safety="safe", response_toxicity=[], response_refusal=[])

    return await service.evaluate_response(text, response_text)


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "main:app",
        host=s.api.host,
        port=s.api.port,
        reload=False,
        log_level="info",
    )
