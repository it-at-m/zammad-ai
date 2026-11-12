"""Utility helpers for API request validation and request processing."""

import json
from secrets import compare_digest
from typing import Any

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from starlette.routing import get_route_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.contextvars import clear_contextvars

from app.preparser.service import PreparserService
from app.settings.settings import ZammadAISettings, get_settings
from app.usecases.registry import UseCaseRegistry
from app.utils.logging import bind_usecase, getLogger

settings: ZammadAISettings = get_settings()
logger = getLogger("zammad-ai.api.v1.utils")

USECASE_API_PATHS = frozenset({"/api/v1/triage", "/api/v1/answer"})
USECASE_BODY_METHODS = frozenset({"POST"})


def check_api_key(provided_key: str | HTTPAuthorizationCredentials | None) -> bool:
    """Check if the provided API key or bearer credentials match the expected API key from settings.

    Args:
        provided_key (str | HTTPAuthorizationCredentials | None): The API key provided in the request header,
            or the HTTPAuthorizationCredentials returned by `HTTPBearer`.

    Returns:
        bool: True if the provided API key is valid, False otherwise.
    """
    expected_key: str | None = settings.api.api_key
    if expected_key is None:
        # If no API key is set in settings, allow all requests
        return True
    if provided_key is None:
        return False

    if isinstance(provided_key, HTTPAuthorizationCredentials):
        provided_value = provided_key.credentials
    else:
        provided_value = provided_key

    return compare_digest(provided_value, expected_key)


def get_preparsed_text(request: Request | None, text: str, preparser_service: PreparserService | None = None) -> str:
    """Return preparsed text using the given or request-scoped preparser service.

    Uses ``preparser_service`` when provided (e.g. the selected usecase runtime's
    service); otherwise fetches ``request.app.state.preparser_service`` and calls
    ``preparse`` on the provided text. If anything fails, logs the error and returns
    the original text.

    This centralizes the preparser logic to keep behavior consistent across endpoints.
    """
    try:
        preparser = (
            preparser_service
            if preparser_service is not None
            else (request.app.state.preparser_service if request is not None else None)
        )
        if preparser is not None:
            return preparser.preparse(text)
    except Exception as e:  # pragma: no cover - defensive  # noqa: F841
        logger.error("Preparser failed; continuing with original text", exc_info=True)
    return text


class UsecaseLoggingMiddleware:
    """Bind the request's usecase to the logging context for the whole request lifecycle.

    The middleware runs inline in the request task before any inner middleware
    spawns tasks, so the binding is visible to endpoint logs and to the uvicorn
    access log, which uvicorn emits when the response headers are sent. The
    logging context is cleared per request so a usecase never leaks into
    unrelated requests. Requests without a resolvable usecase log without one.

    Endpoints whose usecase is resolved from the JSON body must be listed in
    `USECASE_API_PATHS` for the binding to apply. Only requests with a method
    in `USECASE_BODY_METHODS` have their body collected for that resolution,
    and only up to `max_parse_body_bytes`; other requests pass their receive
    through untouched.
    """

    def __init__(self, app: ASGIApp, registry: UseCaseRegistry, max_parse_body_bytes: int) -> None:
        """Wrap the ASGI app with usecase-aware request logging."""
        self.app = app
        self.registry = registry
        self.max_parse_body_bytes = max_parse_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Clear the logging context and bind the resolved usecase for HTTP requests."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        clear_contextvars()
        if get_route_path(scope) in USECASE_API_PATHS:
            usecase, receive = await self._resolve_usecase(scope, receive)
            bind_usecase(usecase)
        await self.app(scope, receive, send)

    async def _resolve_usecase(self, scope: Scope, receive: Receive) -> tuple[str | None, Receive]:
        """Consume the request body once and resolve the requested usecase name.

        Requests without a method that carries a parseable JSON body on the
        usecase endpoints are not parsed and pass their receive through
        untouched, so their bodies are never drained. Returns the usecase name
        when it is known (an explicitly requested configured usecase, or the
        sole configured usecase) and a receive callable that replays the
        consumed body for the downstream app.
        """
        if scope["method"] not in USECASE_BODY_METHODS:
            return None, receive
        body, disconnected, over_limit, replay_receive = await _read_body(receive, self.max_parse_body_bytes)
        if disconnected or over_limit:
            return None, replay_receive
        try:
            payload: Any = json.loads(body) if body else {}
        except ValueError:
            return None, replay_receive
        if not isinstance(payload, dict):
            return None, replay_receive
        requested = payload.get("usecase")
        if isinstance(requested, str) and requested:
            return (requested if requested in self.registry.runtimes else None), replay_receive
        if len(self.registry.runtimes) == 1:
            return next(iter(self.registry.runtimes.values())).settings.usecase.name, replay_receive
        return None, replay_receive


async def _read_body(receive: Receive, max_parse_body_bytes: int) -> tuple[bytes, bool, bool, Receive]:
    """Consume the body stream up to max_parse_body_bytes and return the parseable prefix.

    Messages consumed while the accumulated body stays within the limit are
    cached for parsing and replay. The first message that would exceed the
    limit is cached as well and ends the collection, so buffering stays
    bounded; the returned receive then delegates further reads to the original
    receive so the downstream app still receives the complete body. Returns
    the buffered body (empty when the limit was exceeded), a disconnect flag,
    an over-limit flag, and that receive callable.
    """
    cached: list[Message] = []
    size = 0
    disconnected = False
    over_limit = False
    delegate = False
    while True:
        message: Message = await receive()
        if message["type"] == "http.request":
            chunk = message.get("body", b"")
            if not over_limit and size + len(chunk) > max_parse_body_bytes:
                over_limit = True
                delegate = bool(message.get("more_body", False))
                cached.append(message)
                break
            cached.append(message)
            size += len(chunk)
            if not message.get("more_body", False):
                break
        elif message["type"] == "http.disconnect":
            disconnected = True
            break
    body = b"" if over_limit else b"".join(message.get("body", b"") for message in cached)
    replay_receive = _replay_receive([] if disconnected else cached, receive, delegate)
    return body, disconnected, over_limit, replay_receive


def _replay_receive(cached: list[Message], receive: Receive, delegate: bool) -> Receive:
    """Return a receive callable that replays cached body messages once.

    After the cached messages are replayed, the returned receive either
    delegates to the original receive (when body messages beyond the cache
    still have to reach the downstream app) or reports a disconnect, matching
    the previous fully-drained replay behavior.
    """
    index = 0

    async def replay() -> Message:
        nonlocal index
        if index < len(cached):
            message = cached[index]
            index += 1
            return message
        if delegate:
            return await receive()
        return {"type": "http.disconnect"}

    return replay
