"""Tests for usecase selection in the HTTP API endpoints."""

from app.settings.usecase import UseCaseMatch, UseCaseSettings


def _multi_usecases() -> list[UseCaseSettings]:
    """Return two usecase definitions for multi-usecase selection tests."""
    return [
        UseCaseSettings(
            name="kb-help",
            description="Knowledge base help",
            match=[UseCaseMatch(request_type="kb")],
        ),
        UseCaseSettings(
            name="other",
            description="Other requests",
            match=[UseCaseMatch(request_type="other")],
        ),
    ]


def test_triage_uses_sole_runtime_without_usecase_field(test_client_factory) -> None:
    """A sole configured runtime serves triage requests that omit the usecase field."""
    with test_client_factory() as client:
        response = client.post("/api/v1/triage", json={"text": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["triage"]["category"]["name"] == "category-default"
    assert body["triage"]["reasoning"] == "stub:default"
    assert body["session_id"]


def test_triage_routes_to_requested_usecase(test_client_factory) -> None:
    """An explicit usecase field selects the matching runtime's triage service."""
    with test_client_factory(usecases=_multi_usecases()) as client:
        response = client.post("/api/v1/triage", json={"text": "hello", "usecase": "other"})

    assert response.status_code == 200
    body = response.json()
    assert body["triage"]["category"]["name"] == "category-other"
    assert body["triage"]["reasoning"] == "stub:other"


def test_triage_rejects_unknown_usecase(test_client_factory) -> None:
    """An unknown usecase name is rejected with a 422 response."""
    with test_client_factory(usecases=_multi_usecases()) as client:
        response = client.post("/api/v1/triage", json={"text": "hello", "usecase": "nope"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown usecase"


def test_triage_requires_usecase_when_multiple_configured(test_client_factory) -> None:
    """Omitting the usecase field with multiple runtimes is rejected with a 422 response."""
    with test_client_factory(usecases=_multi_usecases()) as client:
        response = client.post("/api/v1/triage", json={"text": "hello"})

    assert response.status_code == 422
    assert response.json()["detail"] == "usecase is required when multiple usecases are configured"


def test_answer_uses_sole_runtime_without_usecase_field(test_client_factory) -> None:
    """A sole configured runtime serves answer requests that omit the usecase field."""
    with test_client_factory() as client:
        response = client.post(
            "/api/v1/answer",
            json={"text": "hello", "category": "Unknown", "action": "No Action"},
        )

    assert response.status_code == 200
    assert response.json()["response"] == "answer from default"


def test_answer_routes_to_requested_usecase(test_client_factory) -> None:
    """An explicit usecase field selects the matching runtime's action service."""
    with test_client_factory(usecases=_multi_usecases()) as client:
        response = client.post(
            "/api/v1/answer",
            json={"text": "hello", "category": "Unknown", "action": "No Action", "usecase": "kb-help"},
        )

    assert response.status_code == 200
    assert response.json()["response"] == "answer from kb-help"


def test_answer_rejects_unknown_usecase(test_client_factory) -> None:
    """An unknown usecase name is rejected with a 422 response."""
    with test_client_factory(usecases=_multi_usecases()) as client:
        response = client.post(
            "/api/v1/answer",
            json={"text": "hello", "category": "Unknown", "action": "No Action", "usecase": "nope"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown usecase"


def test_answer_requires_usecase_when_multiple_configured(test_client_factory) -> None:
    """Omitting the usecase field with multiple runtimes is rejected with a 422 response."""
    with test_client_factory(usecases=_multi_usecases()) as client:
        response = client.post(
            "/api/v1/answer",
            json={"text": "hello", "category": "Unknown", "action": "No Action"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "usecase is required when multiple usecases are configured"


def test_status_endpoints_reflect_configured_usecases(test_client_factory) -> None:
    """The status endpoints report the configured usecases and stay healthy."""
    with test_client_factory(usecases=_multi_usecases()) as client:
        health = client.get("/api/v1/health")
        usecases = client.get("/api/v1/usecases")

    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert usecases.status_code == 200
    assert usecases.json() == [
        {"name": "kb-help", "description": "Knowledge base help"},
        {"name": "other", "description": "Other requests"},
    ]
