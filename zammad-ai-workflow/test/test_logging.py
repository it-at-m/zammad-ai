"""Tests for logging configuration and structlog renderers."""

import json
import logging
from types import SimpleNamespace
from typing import Any, cast

import structlog
from starlette.types import Message, Receive, Scope, Send
from structlog.contextvars import clear_contextvars, get_contextvars

from app.api.v1.utils import UsecaseLoggingMiddleware
from app.usecases.registry import UseCaseRegistry
from app.utils.logging import (
    StaticAssetFilter,
    bind_usecase,
    build_json_formatter,
    build_plain_formatter,
    get_log_config,
    reset_logging_state,
    unbind_usecase,
    usecase_logging,
)


def _make_record(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="zammad-ai.tests",
        level=level,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=(),
        exc_info=None,
    )


def _fake_registry(*names: str) -> UseCaseRegistry:
    """Return a registry-like object exposing one runtime per given usecase name."""
    return cast(
        UseCaseRegistry,
        SimpleNamespace(
            runtimes={
                name: SimpleNamespace(settings=SimpleNamespace(usecase=SimpleNamespace(name=name))) for name in names
            }
        ),
    )


def _http_scope(path: str, method: str = "POST") -> Scope:
    return {"type": "http", "method": method, "path": path, "headers": []}  # type: ignore[return-value]


def _body_receive(body: bytes) -> Receive:
    """Return a receive callable that yields one body message and then disconnects."""
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


async def _run_middleware(
    registry: UseCaseRegistry,
    scope: Scope,
    receive: Receive,
) -> tuple[dict[str, Any], bytes]:
    """Run UsecaseLoggingMiddleware against a dummy app and return its contextvars and the body it received."""
    captured: dict[str, Any] = {}
    received: list[bytes] = []

    async def send(message: Message) -> None:
        return None

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        captured.update(get_contextvars())
        message = await receive()
        received.append(message.get("body", b""))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    middleware = UsecaseLoggingMiddleware(app=app, registry=registry)
    await middleware(scope, receive, send)
    return captured, b"".join(received)


def test_build_json_formatter_formats_stdlib_records() -> None:
    """JSON formatter should render stdlib log records with extra fields."""
    formatter = build_json_formatter()
    record = logging.LogRecord(
        name="zammad-ai.tests",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Hello %s",
        args=("World",),
        exc_info=None,
    )
    record.request_id = "req-123"

    rendered = formatter.format(record)
    payload = json.loads(rendered)

    assert payload["event"] == "Hello World"
    assert payload["logger"] == "zammad-ai.tests"
    assert payload["level"] == "info"
    assert payload["request_id"] == "req-123"
    assert "timestamp" in payload


def test_build_plain_formatter_formats_stdlib_records() -> None:
    """Plain formatter should keep messages readable while showing extra fields."""
    formatter = build_plain_formatter()
    record = logging.LogRecord(
        name="zammad-ai.tests",
        level=logging.WARNING,
        pathname=__file__,
        lineno=20,
        msg="Problem detected",
        args=(),
        exc_info=None,
    )
    record.ticket_id = 42

    rendered = formatter.format(record)

    assert "Problem detected" in rendered
    assert "ticket_id=42" in rendered
    assert "warning" in rendered


def test_static_asset_filter_blocks_frontend_assets() -> None:
    """Static asset requests should not reach the access log."""
    filter_ = StaticAssetFilter()

    blocked = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg='10.0.0.1:1234 - "GET /feedback/assets/Index.js HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    allowed = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=21,
        msg='10.0.0.1:1234 - "GET /api/v1/health HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )

    assert filter_.filter(blocked) is False
    assert filter_.filter(allowed) is True


def test_reset_logging_state_resets_structlog_defaults() -> None:
    """Reset should clear custom structlog configuration between tests."""
    structlog.configure(processors=[])

    reset_logging_state()

    assert structlog.is_configured() is False


def test_get_log_config_prefers_explicit_json_format_in_development(
    monkeypatch,
    settings_factory,
) -> None:
    """Explicit JSON format should win over development mode defaults."""
    settings = settings_factory(mode="development")
    settings.log.format = "json"
    monkeypatch.setattr("app.utils.logging.get_settings", lambda: settings, raising=False)
    monkeypatch.setattr("app.settings.get_settings", lambda: settings)

    log_config = get_log_config()

    assert log_config["handlers"]["console"]["formatter"] == "json"
    assert log_config["handlers"]["httpx"]["formatter"] == "json"


def test_get_log_config_filters_uvicorn_access_assets(
    monkeypatch,
    settings_factory,
) -> None:
    """Uvicorn access logs should suppress static frontend and feedback asset requests."""
    reset_logging_state()
    settings = settings_factory(mode="development")
    monkeypatch.setattr("app.utils.logging.get_settings", lambda: settings, raising=False)
    monkeypatch.setattr("app.settings.get_settings", lambda: settings)

    log_config = get_log_config()

    assert "static_asset_filter" in log_config["filters"]
    assert log_config["loggers"]["uvicorn.access"]["filters"] == ["static_asset_filter"]


def test_get_log_config_reduces_faststream_noise(
    monkeypatch,
    settings_factory,
) -> None:
    """FastStream logs should stay quiet unless something unusual happens."""
    reset_logging_state()
    settings = settings_factory(mode="development")
    monkeypatch.setattr("app.utils.logging.get_settings", lambda: settings, raising=False)
    monkeypatch.setattr("app.settings.get_settings", lambda: settings)

    log_config = get_log_config()

    assert log_config["loggers"]["faststream"]["level"] == "INFO"


def test_usecase_logging_adds_usecase_extra_to_stdlib_records() -> None:
    """Records emitted inside usecase_logging should carry the usecase as extra."""
    clear_contextvars()
    formatter = build_json_formatter()

    with usecase_logging("kb-help"):
        payload = json.loads(formatter.format(_make_record("Processing ticket")))

    assert payload["usecase"] == "kb-help"


def test_usecase_logging_shows_usecase_in_plain_renderer() -> None:
    """The plain renderer should include the bound usecase as well."""
    clear_contextvars()
    formatter = build_plain_formatter()

    with usecase_logging("kb-help"):
        rendered = formatter.format(_make_record("Processing ticket"))

    assert "usecase='kb-help'" in rendered or "usecase=kb-help" in rendered


def test_usecase_logging_removes_binding_after_exit() -> None:
    """Records emitted after the context should not carry a usecase."""
    clear_contextvars()
    formatter = build_json_formatter()

    with usecase_logging("kb-help"):
        pass

    payload = json.loads(formatter.format(_make_record("After context")))

    assert "usecase" not in payload


def test_usecase_logging_restores_outer_binding() -> None:
    """Nested contexts should restore the outer usecase on exit."""
    clear_contextvars()
    formatter = build_json_formatter()

    with usecase_logging("outer"):
        with usecase_logging("inner"):
            inner = json.loads(formatter.format(_make_record("Inner")))
        outer = json.loads(formatter.format(_make_record("Outer")))

    assert inner["usecase"] == "inner"
    assert outer["usecase"] == "outer"


def test_usecase_logging_without_name_binds_nothing() -> None:
    """A missing usecase name should leave the logging context untouched."""
    clear_contextvars()
    formatter = build_json_formatter()

    with usecase_logging(None):
        payload = json.loads(formatter.format(_make_record("No usecase")))

    assert "usecase" not in payload


def test_bind_and_unbind_usecase_control_the_context() -> None:
    """bind_usecase should add the extra and unbind_usecase should remove it."""
    clear_contextvars()
    formatter = build_json_formatter()

    bind_usecase("kb-help")
    bound = json.loads(formatter.format(_make_record("Bound")))
    unbind_usecase()
    unbound = json.loads(formatter.format(_make_record("Unbound")))

    assert bound["usecase"] == "kb-help"
    assert "usecase" not in unbound


def test_bind_usecase_ignores_empty_name() -> None:
    """An empty usecase name should not bind anything."""
    clear_contextvars()
    formatter = build_json_formatter()

    bind_usecase("")
    payload = json.loads(formatter.format(_make_record("Empty name")))

    assert "usecase" not in payload


def test_bind_usecase_persists_after_calling_function_returns() -> None:
    """A persistent binding must survive the calling function's return.

    uvicorn emits the access log when the response headers are sent, which
    happens after an endpoint function returned, so endpoint-level bindings
    have to stay active instead of being scoped to the function body.
    """
    clear_contextvars()
    formatter = build_json_formatter()

    def endpoint() -> None:
        bind_usecase("kb-help")
        return None

    endpoint()
    payload = json.loads(formatter.format(_make_record("Access log after endpoint returned")))

    assert payload["usecase"] == "kb-help"


async def test_middleware_binds_requested_usecase_for_triage_request() -> None:
    """The middleware should bind the usecase requested in the request body."""
    clear_contextvars()
    body = json.dumps({"text": "hello", "usecase": "kb-help"}).encode()

    captured, _ = await _run_middleware(
        _fake_registry("kb-help", "other"), _http_scope("/api/v1/triage"), _body_receive(body)
    )

    assert captured["usecase"] == "kb-help"


async def test_middleware_binds_sole_usecase_when_request_omits_it() -> None:
    """With a single configured usecase, requests without a usecase field bind it."""
    clear_contextvars()
    body = json.dumps({"text": "hello"}).encode()

    captured, _ = await _run_middleware(_fake_registry("kb-help"), _http_scope("/api/v1/answer"), _body_receive(body))

    assert captured["usecase"] == "kb-help"


async def test_middleware_binds_nothing_for_unknown_usecase() -> None:
    """An unknown requested usecase should not be bound."""
    clear_contextvars()
    body = json.dumps({"text": "hello", "usecase": "nope"}).encode()

    captured, _ = await _run_middleware(_fake_registry("kb-help"), _http_scope("/api/v1/triage"), _body_receive(body))

    assert "usecase" not in captured


async def test_middleware_binds_nothing_without_usecase_in_multi_usecase_mode() -> None:
    """With multiple usecases, a request without a usecase field logs without one."""
    clear_contextvars()
    body = json.dumps({"text": "hello"}).encode()

    captured, _ = await _run_middleware(
        _fake_registry("kb-help", "other"), _http_scope("/api/v1/triage"), _body_receive(body)
    )

    assert "usecase" not in captured


async def test_middleware_clears_stale_binding_for_other_paths() -> None:
    """Requests to endpoints without a usecase must not inherit a stale binding."""
    clear_contextvars()
    bind_usecase("stale")

    captured, _ = await _run_middleware(
        _fake_registry("kb-help"), _http_scope("/api/v1/health", method="GET"), _body_receive(b"")
    )

    assert "usecase" not in captured


async def test_middleware_replays_consumed_body_to_the_app() -> None:
    """The downstream app must still receive the full request body."""
    clear_contextvars()
    body = json.dumps({"text": "hello", "usecase": "kb-help"}).encode()

    _, received_body = await _run_middleware(
        _fake_registry("kb-help"), _http_scope("/api/v1/triage"), _body_receive(body)
    )

    assert received_body == body


async def test_middleware_leaves_binding_active_for_the_response_phase() -> None:
    """The binding must still be active after the downstream app returned.

    uvicorn emits the access log from the response send call, which happens
    after the app returned, so the binding has to outlive the app call.
    """
    clear_contextvars()
    body = json.dumps({"text": "hello", "usecase": "kb-help"}).encode()

    async def send(message: Message) -> None:
        return None

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        return None

    middleware = UsecaseLoggingMiddleware(app=app, registry=_fake_registry("kb-help"))
    await middleware(_http_scope("/api/v1/triage"), _body_receive(body), send)
    payload = json.loads(build_json_formatter().format(_make_record("Access log")))

    assert payload["usecase"] == "kb-help"
