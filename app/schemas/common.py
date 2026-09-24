"""Response envelope shared by every endpoint, per CLAUDE.md §4."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    """Machine-readable error code plus a human-readable message."""

    code: str
    message: str
    details: Any | None = None


class Envelope[T](BaseModel):
    """`{"data": ..., "error": ...}` — exactly one of the two is non-null."""

    data: T | None = None
    error: ErrorBody | None = None
