"""slm-guardrails FastAPI entrypoint with endpoints and metrics."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from guardrail_app.guardrails.service import GuardrailService
from guardrail_app.models.guardrails import GuardrailResponseResult, GuardrailResult, PromptRequest, ResponseRequest
from guardrail_app.settings.settings import ServiceSettings, get_settings
from guardrail_app.utils.logging import getLogger
from prometheus_client import make_asgi_app

logger = getLogger("slm-guardrails")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: initialize and gracefully shutdown the service.

    Replaces deprecated on_event startup/shutdown hooks.
    """
    # Initialize the guardrail model eagerly. If the model cannot be loaded
    # we want startup to fail loudly so callers and orchestrators notice.
    settings = get_settings()
    service = GuardrailService(settings.guardrails)
    app.state.service = service
    logger.info("slm-guardrails started")
    # Yield control to serve requests
    try:
        yield
    finally:
        logger.info("slm-guardrails shutting down")
        await service.close()


app = FastAPI(title="slm-guardrails", version="0.1.0", lifespan=lifespan)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


def _get_service(request: Request) -> GuardrailService:
    return request.app.state.service


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "ok"}


def _auth_check(request: Request, settings: ServiceSettings) -> None:
    token = settings.api.auth_token
    if token:
        header = request.headers.get("authorization", "")
        if not header:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        provided = parts[1].strip()
        if not hmac.compare_digest(provided, token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.post("/api/v1/guardrails/prompt", response_model=GuardrailResult)
async def evaluate_prompt(
    request: Request,
    payload: PromptRequest,
    settings: ServiceSettings = Depends(get_settings),
    service: GuardrailService = Depends(_get_service),
) -> GuardrailResult:
    """Evaluate a user prompt text for safety via the model service."""
    _auth_check(request, settings)
    thr = settings.guardrails.confidence_threshold if payload.threshold is None else float(payload.threshold)
    model_id = getattr(payload, "model", None) or settings.guardrails.default_model
    # If the model is configured but wasn't loaded at startup (tests or lazy load
    # scenarios), attempt to load it on-demand. If loading fails, return 400.
    if not service.has_model(model_id):
        if model_id in settings.guardrails.models:
            try:
                # _load_model is synchronous; allow it to run and register the model
                service._load_model(model_id, settings.guardrails.models[model_id])
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown model: {model_id}")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown model: {model_id}")
    # Enforce configured maximum input length
    max_len = settings.api.max_input_length
    if max_len and len(payload.text or "") > max_len:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Input text length exceeds maximum allowed ({max_len} characters)",
        )
    return await service.evaluate(payload.text, threshold=thr, model_id=model_id)


@app.post("/api/v1/guardrails/response", response_model=GuardrailResponseResult)
async def evaluate_response(
    request: Request,
    payload: ResponseRequest,
    settings: ServiceSettings = Depends(get_settings),
    service: GuardrailService = Depends(_get_service),
) -> GuardrailResponseResult:
    """Evaluate a generated response (with prompt context) for safety."""
    _auth_check(request, settings)
    thr = settings.guardrails.confidence_threshold if payload.threshold is None else float(payload.threshold)
    model_id = getattr(payload, "model", None) or settings.guardrails.default_model
    # Allow on-demand loading for configured models that may not have been
    # initialized at startup (helps tests and lazy deployments).
    if not service.has_model(model_id):
        if model_id in settings.guardrails.models:
            try:
                service._load_model(model_id, settings.guardrails.models[model_id])
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown model: {model_id}")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown model: {model_id}")
    # Enforce configured maximum input length for both prompt and response
    max_len = settings.api.max_input_length
    if max_len and len(payload.text or "") + len(payload.response or "") > max_len:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Input text length exceeds maximum allowed ({max_len} characters)",
        )
    return await service.evaluate_response(payload.text, payload.response, threshold=thr, model_id=model_id)


@app.get("/ready")
async def ready(request: Request) -> dict[str, dict[str, bool]]:
    """Readiness endpoint that reports model availability."""
    svc: GuardrailService = request.app.state.service
    models_ready = {k: svc.has_model(k) for k in svc._models.keys()}
    return {"models": models_ready}


@app.get("/api/v1/models")
async def list_models(
    request: Request,
    settings: ServiceSettings = Depends(get_settings),
    service: GuardrailService = Depends(_get_service),
) -> dict:
    """Return configured guardrail models with availability and configuration.

    The response maps model_id -> {available: bool, config: dict}.
    """
    svc: GuardrailService = service
    result: dict[str, dict] = {}
    for model_id, cfg in settings.guardrails.models.items():
        available = svc.has_model(model_id)
        cfg_dict = cfg.model_dump() if cfg else {}
        result[model_id] = {"available": available, "config": cfg_dict}
    return {"models": result}


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
