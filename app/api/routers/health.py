"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.common import Envelope, ErrorBody

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> Envelope[dict[str, str]]:
    """Liveness probe: process is up. Does not touch the database."""
    return Envelope(data={"status": "ok"})


@router.get("/health/ready", response_model=None)
async def health_ready(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Envelope[dict[str, str]] | JSONResponse:
    """Readiness probe: confirms the database is reachable."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        envelope = Envelope[dict[str, str]](
            data=None,
            error=ErrorBody(code="not_ready", message="Database is unreachable.", details=None),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=envelope.model_dump(mode="json"),
        )
    return Envelope(data={"status": "ready"})
