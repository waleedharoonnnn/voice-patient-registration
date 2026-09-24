"""Domain exceptions and global exception handlers that produce the response envelope.

Every error path (domain exceptions, FastAPI HTTPException, Pydantic validation
failures, and unhandled exceptions) is converted to the same
`{"data": null, "error": {...}}` shape so clients never need to special-case a
success/error response format.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.schemas.common import Envelope, ErrorBody

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for domain exceptions that map to a specific HTTP status + code."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ValidationFailedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_failed"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


def _envelope_response(status_code: int, error: ErrorBody) -> JSONResponse:
    envelope = Envelope[Any](data=None, error=error)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(envelope.model_dump(mode="json")),
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _envelope_response(
        exc.status_code, ErrorBody(code=exc.code, message=exc.message, details=exc.details)
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed."
    return _envelope_response(
        exc.status_code,
        ErrorBody(code=_code_for_status(exc.status_code), message=message, details=None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = jsonable_encoder(exc.errors())
    # A body that isn't parseable JSON is a malformed request (400), not a well-formed
    # request with invalid values (422) — see CLAUDE.md §4.
    if any(error.get("type") == "json_invalid" for error in exc.errors()):
        return _envelope_response(
            status.HTTP_400_BAD_REQUEST,
            ErrorBody(
                code="malformed_request", message="Request body is not valid JSON.", details=None
            ),
        )
    return _envelope_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorBody(code="validation_failed", message="Request validation failed.", details=details),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception while processing request",
        extra={"request_id": request_id, "path": request.url.path},
    )
    return _envelope_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorBody(code="internal_error", message="An unexpected error occurred.", details=None),
    )


def _code_for_status(status_code: int) -> str:
    return {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "unauthorized",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_failed",
        status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    }.get(status_code, "error")


def register_exception_handlers(app: FastAPI) -> None:
    """Wire every handler needed so no error path ever bypasses the envelope."""
    # The type ignores below: Starlette types handlers as taking `Exception`, but each
    # handler here is (correctly) narrowed to the exception class it's registered for.
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
