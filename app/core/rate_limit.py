"""Per-client-IP rate limiting, applied to every route by path (fail-closed).

Uses slowapi's `Limiter` for its storage and moving-window limiter (public `.limiter`
property), but NOT slowapi's own middleware: `SlowAPIMiddleware` finds a route's handler
by scanning `app.routes`, which on current FastAPI no longer contains the individual
routes of included routers — it found no handler, treated that as "exempt", and silently
limited nothing. Matching on the URL path instead means every new route is limited by
default and exemptions are one explicit, reviewable list.
"""

from __future__ import annotations

import math
import time

from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

limiter = Limiter(key_func=get_remote_address)

# Paths never rate limited:
# - /health*: polled constantly by load balancers and container health checks.
# - /vapi/webhook: every Vapi request comes from a few shared Vapi IPs, so a per-IP cap
#   would throttle concurrent live calls (a dropped tool call is dead air on the phone).
#   It is authenticated by a shared secret compared in constant time.
# - /static: the dashboard's CSS.
EXEMPT_PATH_PREFIXES: tuple[str, ...] = ("/health", "/vapi/webhook", "/static/")


class RateLimitMiddleware:
    """Reject over-limit requests with an enveloped 429 and a Retry-After header."""

    def __init__(self, app: ASGIApp, *, limit: str) -> None:
        self.app = app
        self.limit = parse(limit)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "http" or path.startswith(EXEMPT_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        key = get_remote_address(Request(scope))
        if limiter.limiter.hit(self.limit, key):
            await self.app(scope, receive, send)
            return

        reset_at, _remaining = limiter.limiter.get_window_stats(self.limit, key)
        retry_after = max(1, math.ceil(reset_at - time.time()))
        response = JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={
                "data": None,
                "error": {
                    "code": "rate_limited",
                    "message": "Too many requests. Please slow down.",
                    "details": {"retry_after_seconds": retry_after},
                },
            },
        )
        await response(scope, receive, send)
