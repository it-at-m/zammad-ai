import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from logging import Logger
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from prometheus_client import Counter, Histogram
from starlette.responses import Response

from app.action.service import ActionService, get_action_service
from app.answer import get_answer_service
from app.answer.service import AnswerService
from app.frontend import mount_frontend
from app.kafka.broker import build_router
from app.models.api_v1 import HealthCheckResponse
from app.settings import ZammadAISettings, get_settings
from app.triage import get_triage_service
from app.triage.triage import TriageService
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application startup and shutdown by initializing and cleaning shared services.

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

        logger.info("Initializing shared Triage instance")
        app.state.triage_service: TriageService = get_triage_service(settings=settings)
        app.state.answer_service: AnswerService = get_answer_service(settings=settings)
        app.state.action_service: ActionService = get_action_service(settings=settings, answer_service=app.state.answer_service)

        yield

        logger.info("Shutting down shared Triage instance")
        set_status("shutdown")
        try:
            await app.state.triage_service.cleanup()
            await app.state.answer_service.cleanup()
            await app.state.action_service.cleanup()
        except asyncio.CancelledError:
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
kafka_router, _ = build_router(settings=settings)

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
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=route_path, status=str(status_code)).observe(perf_counter() - start_time)

    return response


# Include Kafka router (this handles broker lifecycle automatically)
backend.include_router(
    router=kafka_router,
)


@kafka_router.after_startup
async def mark_ready(_app: FastAPI) -> None:
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

if settings.frontend.enabled:
    backend = mount_frontend(app=backend, frontend_settings=settings.frontend)

if not settings.frontend.enabled and settings.mode == "development":
    logger.info("Frontend is disabled, rerouting root path to API docs")

    @backend.get("/", include_in_schema=False)
    async def reroute_to_docs() -> RedirectResponse:
        """
        Redirect root requests to the API documentation page.

        Returns:
            RedirectResponse: A response that redirects the client to "/api/docs".
        """
        return RedirectResponse(url="/api/docs")


@backend.get("/api/v1/health", tags=["health"])
async def health_check() -> HealthCheckResponse:
    """
    Provide a basic application health check response.

    Returns:
        HealthCheckResponse: An instance containing the application's default health status.
    """
    return HealthCheckResponse()
