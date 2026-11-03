"""Integration tests for the Langfuse client against a local HTTP server."""

import base64
import json
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest
from langfuse._client.resource_manager import LangfuseResourceManager

from app.observe.langfuse import LangfuseClient, LangfuseError

TRACE_ID = "e740f6733e6e726735761552c952dc18"


class _LangfuseStubServer:
    """Minimal Langfuse API stub serving trace and score endpoints."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, list[str]]]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                auth = self.headers.get("Authorization", "")
                stub.requests.append((parsed.path, auth, query))

                expected_auth = "Basic " + base64.b64encode(b"pk-test:sk-test").decode()
                if auth != expected_auth:
                    self._send_json(401, {"detail": "unauthorized"})
                elif parsed.path == f"/api/public/traces/{TRACE_ID}":
                    self._send_json(
                        200,
                        {"id": TRACE_ID, "input": "Eine Anfrage", "output": "Eine statische Antwort"},
                    )
                elif parsed.path == "/api/public/traces/missing":
                    self._send_json(404, {"detail": "not found"})
                elif parsed.path == "/api/public/v3/scores":
                    self._send_json(
                        200,
                        {
                            "data": [
                                {
                                    "id": "score-1",
                                    "projectId": "test-project",
                                    "name": "user-thumbs",
                                    "source": "API",
                                    "timestamp": "2026-01-01T00:00:00Z",
                                    "environment": "default",
                                    "createdAt": "2026-01-01T00:00:00Z",
                                    "updatedAt": "2026-01-01T00:00:00Z",
                                    "dataType": "BOOLEAN",
                                    "value": True,
                                }
                            ],
                            "meta": {"limit": 100},
                        },
                    )
                else:
                    self._send_json(404, {"detail": "not found"})

            def _send_json(self, status: int, body: dict[str, object]) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object, **kwargs: object) -> None:
                pass

        self._http_server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._http_server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._http_server.server_address[1]}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._http_server.shutdown()
        self._http_server.server_close()


@pytest.fixture
def langfuse_stub(monkeypatch: pytest.MonkeyPatch) -> Generator[_LangfuseStubServer, None, None]:
    """Serve a stubbed Langfuse API and point the client env at it."""
    # The SDK caches its resource manager per public key; reset it so each test
    # talks to its own stub server instead of a previously shut-down instance.
    LangfuseResourceManager.reset()
    server = _LangfuseStubServer()
    server.start()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", server.base_url)
    yield server
    server.stop()


def test_get_trace_io_and_has_score_against_local_langfuse_api(langfuse_stub: _LangfuseStubServer) -> None:
    """Trace IO and score lookups work through the SDK's configured HTTP client."""
    client = LangfuseClient()

    input_text, output_text, used_documents = client.get_trace_io(trace_id=TRACE_ID)

    assert (input_text, output_text, used_documents) == ("Eine Anfrage", "Eine statische Antwort", "")
    assert client.has_score(trace_id=TRACE_ID, score_name="user-thumbs") is True
    assert client.has_score(trace_id=TRACE_ID, score_name="other-score") is False

    trace_path, trace_auth, trace_query = langfuse_stub.requests[0]
    assert trace_path == f"/api/public/traces/{TRACE_ID}"
    assert trace_auth.startswith("Basic ")
    assert trace_query["fields"] == ["core,io"]

    scores_path, _, scores_query = next(
        request for request in langfuse_stub.requests if request[0] == "/api/public/v3/scores"
    )
    assert scores_path == "/api/public/v3/scores"
    assert scores_query["traceId"] == [TRACE_ID]


def test_get_trace_io_maps_missing_trace_to_langfuse_error(langfuse_stub: _LangfuseStubServer) -> None:
    """A 404 from the Langfuse API surfaces as LangfuseError."""
    client = LangfuseClient()

    with pytest.raises(LangfuseError):
        client.get_trace_io(trace_id="missing")

    assert any(path == "/api/public/traces/missing" for path, _, _ in langfuse_stub.requests)
