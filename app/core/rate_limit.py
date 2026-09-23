"""slowapi rate limiter configuration and its enveloped 429 handler."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.schemas.common import ErrorBody

limiter = Limiter(default_limits=[get_settings().RATE_LIMIT_DEFAULT], key_func=get_remote_address)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    error = ErrorBody(code="rate_limited", message="Too many requests.", details=str(exc.detail))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"data": None, "error": error.model_dump(mode="json")},
    )
