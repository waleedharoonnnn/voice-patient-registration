"""Application factory: wires routers, middleware, and exception handlers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routers import health, patients, providers, vapi
from app.api.routers.dashboard import register_dashboard
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import RateLimitMiddleware
from app.db.session import dispose_engine

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


# Vercel allows at most 500 ms of cleanup after SIGTERM; stay well inside it.
_SHUTDOWN_TIMEOUT_SECONDS = 0.4


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """No startup work (nothing touches the network or disk at import/startup, so cold
    starts stay fast and the read-only serverless filesystem is never written). On
    shutdown, close pooled DB connections — bounded, because the platform kills the
    process after its cleanup window anyway."""
    yield
    try:
        await asyncio.wait_for(dispose_engine(), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("engine dispose did not complete cleanly during shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title="Voice AI Patient Registration API",
        version="0.1.0",
        description=(
            "REST API and Vapi webhook backend for a voice agent that collects, "
            "confirms, and stores US patient demographics."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.ENABLE_API_DOCS else None,
        redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
        openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    )
    app.add_middleware(
        RateLimitMiddleware,
        limit=settings.RATE_LIMIT_DEFAULT,
        client_ip_header=settings.RATE_LIMIT_CLIENT_IP_HEADER,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.ENABLE_HSTS)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)
    # Outermost: reject oversized bodies before any other work happens.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(patients.router)
    app.include_router(vapi.router)
    app.include_router(providers.router)
    register_dashboard(app)
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app


app = create_app()
