"""Integration tests for slm-guardrail FastAPI endpoints.

These tests monkeypatch the model loading to avoid downloading a real model.
"""
# ruff: noqa: D101, D102, D103

from __future__ import annotations

import httpx
from guardrail_app.settings import settings as settings_module
from guardrail_app.settings.settings import APISettings, GuardrailSettings, ModelConfig, ServiceSettings

from main import app


class DummyModel:
    def classify_text(self, text: str, tasks: dict, threshold: float = 0.7):  # noqa: D401 - external signature
        # Return minimal valid shapes based on requested tasks
        if "prompt_safety" in tasks:
            return {
                "prompt_safety": "unsafe",
                "prompt_toxicity": ["pii_exposure"],
                "jailbreak_detection": [],
            }
        if "response_safety" in tasks:
            return {
                "response_safety": "unsafe",
                "response_toxicity": ["pii_exposure"],
                "response_refusal": [],
            }
        return {}


class DummyOpirModel:
    def classify_text(self, text: str, tasks: dict, threshold: float = 0.7):  # noqa: D401 - external signature
        if "prompt_safety" in tasks:
            return {
                "prompt_safety": "safe",
                "prompt_toxicity": [],
                "jailbreak_detection": ["prompt_injection"],
                "label_scores": {
                    "prompt_safety.safe": 0.91,
                    "prompt_safety.unsafe": 0.09,
                    "prompt_toxicity.pii_exposure": 0.02,
                    "jailbreak_detection.prompt_injection": 0.84,
                },
            }
        if "response_safety" in tasks:
            return {
                "response_safety": "safe",
                "response_toxicity": [],
                "response_refusal": ["refusal"],
                "label_scores": {
                    "response_safety.safe": 0.92,
                    "response_safety.unsafe": 0.08,
                    "response_refusal.refusal": 0.88,
                },
            }
        return {"label_scores": {}}


def _patch_settings(monkeypatch, *, enabled: bool = True, auth_token: str | None = None) -> ServiceSettings:
    settings = ServiceSettings(
        api=APISettings(host="127.0.0.1", port=8081, auth_token=auth_token),
        guardrails=GuardrailSettings(offline_mode=True),
    )
    return settings


def _patch_model(monkeypatch) -> None:
    import asyncio

    def fake_load_models(self):
        # populate a single default model used by tests
        self._models = {"default": DummyModel()}
        self._semaphores = {"default": asyncio.Semaphore(1)}

    monkeypatch.setattr("guardrail_app.guardrails.service.GuardrailService._load_models", fake_load_models)


async def test_service_starts_and_loads_opir(monkeypatch) -> None:
    import asyncio

    from guardrail_app.guardrails.service import GuardrailService
    from guardrail_app.settings.settings import ModelConfig

    settings = GuardrailSettings(
        offline_mode=True,
        default_model="fastino",
        models={
            "fastino": ModelConfig(),
            "opir": ModelConfig(hf_model_name="knowledgator/opir-multitask-large-v1.0"),
        },
    )

    def fake_load_model(self, model_id, cfg, gliner_cls):
        if model_id == "opir":
            self._models[model_id] = DummyOpirModel()
        else:
            self._models[model_id] = DummyModel()
        self._semaphores[model_id] = asyncio.Semaphore(1)

    monkeypatch.setattr("guardrail_app.guardrails.service.GuardrailService._load_model", fake_load_model)

    service = GuardrailService(settings)

    assert service.has_model("fastino") is True
    assert service.has_model("opir") is True


async def test_prompt_opir_model(monkeypatch) -> None:
    settings = _patch_settings(monkeypatch)
    settings.guardrails.default_model = "fastino"
    settings.guardrails.models = {
        "fastino": ModelConfig(),
        "opir": ModelConfig(hf_model_name="knowledgator/opir-multitask-large-v1.0"),
    }

    import asyncio

    def fake_load_model(self, model_id, cfg, gliner_cls):
        self._models[model_id] = DummyOpirModel() if model_id == "opir" else DummyModel()
        self._semaphores[model_id] = asyncio.Semaphore(1)

    monkeypatch.setattr("guardrail_app.guardrails.service.GuardrailService._load_model", fake_load_model)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    settings_module.get_settings.cache_clear()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/guardrails/prompt", json={"text": "hello", "model": "opir"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["prompt_safety"] == "safe"
            assert "prompt_injection" in data["jailbreak_detection"]


async def test_healthz_ok(monkeypatch) -> None:
    # Patch model load to avoid heavy imports during tests
    _patch_model(monkeypatch)
    # Clear cached settings so overrides take effect
    settings_module.get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


async def test_prompt_disabled_returns_safe(monkeypatch) -> None:
    # With an empty text the service should quickly return a safe result
    settings = _patch_settings(monkeypatch)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    _patch_model(monkeypatch)
    settings_module.get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/guardrails/prompt", json={"text": ""})
            assert resp.status_code == 200
            data = resp.json()
            assert data["prompt_safety"] == "safe"


async def test_prompt_success(monkeypatch) -> None:
    settings = _patch_settings(monkeypatch)
    _patch_model(monkeypatch)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    settings_module.get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/guardrails/prompt", json={"text": "hello", "threshold": 0.5})
            assert resp.status_code == 200
            data = resp.json()
            assert data["prompt_safety"] == "unsafe"
            assert "pii_exposure" in data["prompt_toxicity"]


async def test_response_success(monkeypatch) -> None:
    settings = _patch_settings(monkeypatch)
    _patch_model(monkeypatch)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    settings_module.get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/guardrails/response",
                json={"text": "t", "response": "r", "threshold": 0.6},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["response_safety"] == "unsafe"
            assert "pii_exposure" in data["response_toxicity"]


async def test_auth_required(monkeypatch) -> None:
    settings = _patch_settings(monkeypatch, auth_token="secret")
    _patch_model(monkeypatch)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    settings_module.get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # No auth header -> 401
            resp = await client.post("/api/v1/guardrails/prompt", json={"text": "hello"})
            assert resp.status_code == 401
            # With header -> 200
            resp2 = await client.post(
                "/api/v1/guardrails/prompt",
                headers={"Authorization": "Bearer secret"},
                json={"text": "hello"},
            )
            assert resp2.status_code == 200
