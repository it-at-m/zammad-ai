"""Shared API error mapping for v1 endpoints."""

from fastapi import HTTPException

from app.errors import (
    AppError,
    GenAIAuthError,
    GenAIContentFilterError,
    GenAIQuotaError,
    GenAITimeoutError,
    TriageCategoryWrongError,
)


def app_error_to_http(error: AppError) -> HTTPException:
    """Map typed application errors to stable HTTP responses for API callers."""
    if isinstance(error, TriageCategoryWrongError):
        return HTTPException(
            status_code=422,
            detail={
                "error": type(error).__name__,
                "message": str(error),
                "retryable": error.retryable,
            },
        )

    if isinstance(error, GenAIQuotaError):
        return HTTPException(
            status_code=429,
            detail={
                "error": type(error).__name__,
                "message": str(error),
                "retryable": error.retryable,
            },
        )

    if isinstance(error, GenAITimeoutError):
        return HTTPException(
            status_code=503,
            detail={
                "error": type(error).__name__,
                "message": str(error),
                "retryable": error.retryable,
            },
        )

    if isinstance(error, GenAIAuthError):
        return HTTPException(
            status_code=502,
            detail={
                "error": type(error).__name__,
                "message": str(error),
                "retryable": error.retryable,
            },
        )

    if isinstance(error, GenAIContentFilterError):
        return HTTPException(
            status_code=422,
            detail={
                "error": type(error).__name__,
                "message": str(error),
                "retryable": error.retryable,
            },
        )

    if error.retryable:
        return HTTPException(
            status_code=503,
            detail={
                "error": type(error).__name__,
                "message": str(error),
                "retryable": error.retryable,
            },
        )

    return HTTPException(
        status_code=422,
        detail={
            "error": type(error).__name__,
            "message": str(error),
            "retryable": error.retryable,
        },
    )


def unexpected_error_to_http() -> HTTPException:
    """Return a generic 500 response for unexpected endpoint failures."""
    return HTTPException(
        status_code=500,
        detail={
            "error": "InternalServerError",
            "message": "Unexpected server error",
            "retryable": True,
        },
    )
