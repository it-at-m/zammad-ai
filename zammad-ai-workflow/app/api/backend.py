"""FastAPI backend wiring for Zammad AI services and routes."""

from asyncio import CancelledError
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from logging import Logger
from socket import create_connection
from time import perf_counter
from urllib.parse import ParseResult, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from prometheus_client import Counter, Histogram
from starlette.responses import Response

from app.action.service import get_action_service
from app.answer import get_answer_service
from app.frontend import mount_feedback_frontend, mount_frontend
from app.models.api_v1 import HealthCheckResponse
from app.preparser.service import get_preparser_service
from app.settings import ZammadAISettings, get_settings
from app.triage import get_triage_service
from app.utils.logging import getLogger
from app.utils.status import set_status, track_activity

from .v1.answer import answer_router
from .v1.triage import triage_router

logger: Logger = getLogger("zammad-ai.api.backend")

HTTP_REQUESTS_TOTAL = Counter(
    name="zammad_ai_http_requests_total",
    documentation="Total HTTP requests processed by FastAPI.",
    labelnames=("method", "path", "status"),
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    name="zammad_ai_http_request_duration_seconds",
    documentation="HTTP request processing duration in seconds.",
    labelnames=("method", "path", "status"),
)


def _parse_bootstrap_servers(broker_url: str) -> list[tuple[str, int]]:
    """Return host and port pairs parsed from a Kafka bootstrap server string."""
    endpoints: list[tuple[str, int]] = []

    for raw_server in broker_url.split(","):
        server: str = raw_server.strip()
        if not server:
            continue

        normalized_server = server if "://" in server else f"//{server}"
        parsed: ParseResult = urlparse(normalized_server)
        if parsed.hostname is None:
            continue

        try:
            port: int | None = parsed.port
        except ValueError:
            logger.warning(
                "Kafka bootstrap server has an invalid port; skipping entry.",
                exc_info=True,
            )
            continue

        endpoints.append((parsed.hostname, port or 9092))

    return endpoints


def _is_kafka_reachable(broker_url: str, timeout_seconds: float = 1.0) -> bool:
    """Check whether at least one Kafka bootstrap server is reachable over TCP."""
    for host, port in _parse_bootstrap_servers(broker_url):
        try:
            with create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            continue

    return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown by initializing and cleaning shared services.

    On startup, attaches `triage_service` and `answer_service` to `app.state` using current settings. On shutdown, awaits each service's `cleanup()` method; `asyncio.CancelledError` raised during cleanup is caught.
    """
    set_status("startup")
    settings: ZammadAISettings = get_settings()
    metrics_server = None
    metrics_thread = None

    try:
        if settings.prometheus.enabled:
            from prometheus_client import start_http_server

            logger.info(msg=f"Starting Prometheus metrics server on port {settings.prometheus.port}")
            try:
                metrics_server, metrics_thread = start_http_server(port=settings.prometheus.port)
            except OSError as e:
                logger.warning(
                    f"Prometheus metrics server could not be started; continuing without metrics export. Error type: {type(e).__name__}",
                    exc_info=True,
                )

        logger.info("Initializing shared Triage, Answer, Action, and Preparser services")
        app.state.triage_service = get_triage_service(settings=settings)
        app.state.answer_service = get_answer_service(settings=settings)
        app.state.action_service = get_action_service(settings=settings, answer_service=app.state.answer_service)
        app.state.preparser_service = get_preparser_service(settings=settings.preparser)

        if kafka_router is None:
            set_status("ready")

        yield

        logger.info("Shutting down shared Triage, Answer and Action services")
        set_status("shutdown")
        try:
            await app.state.triage_service.cleanup()
            await app.state.answer_service.cleanup()
            await app.state.action_service.cleanup()
        except CancelledError:
            logger.info("Cleanup cancelled during shutdown.")
    except Exception as e:
        logger.error(
            f"Error during application lifespan management. Error type: {type(e).__name__}",
            exc_info=True,
        )
        raise
    finally:
        if metrics_server is not None and metrics_thread is not None:
            metrics_server.shutdown()
            metrics_server.server_close()
            metrics_thread.join()
            logger.info("Prometheus metrics server shutdown complete.")


settings: ZammadAISettings = get_settings()

kafka_router = None
if _is_kafka_reachable(settings.kafka.broker_url):
    try:
        from app.kafka.broker import build_router

        kafka_router, _ = build_router(settings=settings)
        logger.info("Kafka broker is reachable; Kafka router enabled.")
    except Exception:
        if settings.kafka.silent_fallback:
            logger.warning(
                "Kafka router could not be initialized; continuing with REST-only mode.",
                exc_info=True,
            )
        else:
            logger.error("Kafka router could not be initialized and silent fallback is disabled.", exc_info=True)
            raise
else:
    if settings.kafka.silent_fallback:
        logger.warning("Kafka broker is not reachable; continuing with REST-only mode.")
    else:
        logger.error("Kafka broker is not reachable and silent fallback is disabled.")
        raise RuntimeError("Kafka broker is not reachable and silent fallback is disabled.")

# Create FastAPI app with lifespan
backend = FastAPI(
    lifespan=lifespan,
    title="Zammad AI Backend",
    description="Backend service for Zammad AI, handling Kafka events and REST API for ticket triage and answer generation.",
    docs_url="/api/docs" if settings.mode == "development" else None,
    redoc_url="/api/redoc" if settings.mode == "development" else None,
)


@backend.middleware("http")
async def prometheus_http_metrics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Collect Prometheus HTTP metrics around each incoming request."""
    start_time: float = perf_counter()
    method: str = request.method
    status_code = 500
    try:
        if request.url.path in ("/triage", "/answer"):
            async with track_activity():
                response: Response = await call_next(request)
                status_code = response.status_code
        else:
            response = await call_next(request)
            status_code = response.status_code
    except Exception:
        raise
    finally:
        route = request.scope.get("route")
        route_path: str = route.path if route is not None and hasattr(route, "path") else "unmatched"
        HTTP_REQUESTS_TOTAL.labels(method=method, path=route_path, status=str(status_code)).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=route_path, status=str(status_code)).observe(
            perf_counter() - start_time
        )

    return response


if kafka_router is not None:
    backend.include_router(router=kafka_router)

    @kafka_router.after_startup
    async def mark_ready(_app: FastAPI) -> None:
        """Mark the application status as ready after Kafka startup completes."""
        set_status("ready")
        logger.info("Kafka broker connected and application startup completed.")


# Mount API routers
backend.include_router(
    router=triage_router,
    prefix="/api/v1",
)

backend.include_router(
    router=answer_router,
    prefix="/api/v1",
)


@backend.get("/api/v1/prompt_versions", tags=["status"])
async def get_prompt_versions() -> dict[str, int | None]:
    """Return the versions of all loaded prompts.

    Returns:
        dict[str, int | None]: A dictionary mapping prompt names to their version numbers.
    """
    prompts = backend.state.triage_service.get_prompt_versions()
    prompts.update(backend.state.answer_service.get_prompt_versions())

    return prompts


@backend.get("/api/v1/health", tags=["health"])
async def health_check() -> HealthCheckResponse:
    """Provide a basic application health check response.

    Returns:
        HealthCheckResponse: An instance containing the application's default health status.
    """
    return HealthCheckResponse()


if settings.frontend.enabled:
    # Mount the feedback frontend first so it is not shadowed by the root frontend mount.
    backend = mount_feedback_frontend(app=backend, settings=settings)
    backend = mount_frontend(app=backend, settings=settings)

if not settings.frontend.enabled and settings.mode == "development":
    logger.info("Frontend is disabled, rerouting root path to API docs")

    @backend.get("/", include_in_schema=False)
    async def reroute_to_docs() -> RedirectResponse:
        """Redirect root requests to the API documentation page.

        Returns:
            RedirectResponse: A response that redirects the client to "/api/docs".
        """
        return RedirectResponse(url="/api/docs")
