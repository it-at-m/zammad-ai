"""Integration tests for slm-guardrail FastAPI endpoints.

These tests monkeypatch the model loading to avoid downloading a real model.
"""
# ruff: noqa: D101, D102, D103

from __future__ import annotations

import httpx
from guardrail_app.settings import settings as settings_module
from guardrail_app.settings.settings import APISettings, GuardrailSettings, ServiceSettings

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


def _patch_settings(monkeypatch, *, enabled: bool = True, auth_token: str | None = None) -> ServiceSettings:
    settings = ServiceSettings(
        api=APISettings(host="127.0.0.1", port=8081, auth_token=auth_token),
        guardrails=GuardrailSettings(enabled=enabled, offline_mode=True),
    )
    return settings


def _patch_model(monkeypatch) -> None:
    def fake_load(self):
        self._model = DummyModel()

    monkeypatch.setattr("guardrail_app.guardrails.service.GuardrailService._load_model", fake_load)


async def test_healthz_ok(monkeypatch) -> None:
    # Prevent model initialization during startup to avoid heavy imports in tests
    monkeypatch.setenv("SLM_GUARDRAIL_GUARDRAILS__ENABLED", "false")
    # Clear cached settings so new env takes effect
    settings_module.get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


async def test_prompt_disabled_returns_safe(monkeypatch) -> None:
    settings = _patch_settings(monkeypatch, enabled=False)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    # Ensure app startup doesn't load the model
    monkeypatch.setenv("SLM_GUARDRAIL_GUARDRAILS__ENABLED", "false")
    settings_module.get_settings.cache_clear()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/guardrails/prompt", json={"text": "hello"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["prompt_safety"] == "safe"


async def test_prompt_success(monkeypatch) -> None:
    settings = _patch_settings(monkeypatch, enabled=True)
    _patch_model(monkeypatch)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    # Ensure startup uses enabled True and re-reads settings
    monkeypatch.setenv("SLM_GUARDRAIL_GUARDRAILS__ENABLED", "true")
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
    settings = _patch_settings(monkeypatch, enabled=True)
    _patch_model(monkeypatch)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    monkeypatch.setenv("SLM_GUARDRAIL_GUARDRAILS__ENABLED", "true")
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
    settings = _patch_settings(monkeypatch, enabled=True, auth_token="secret")
    _patch_model(monkeypatch)
    app.dependency_overrides[settings_module.get_settings] = lambda: settings
    monkeypatch.setenv("SLM_GUARDRAIL_GUARDRAILS__ENABLED", "true")
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
