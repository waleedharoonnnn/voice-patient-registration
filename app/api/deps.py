"""Shared FastAPI dependencies: DB session wiring and API-key auth."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.db.session import get_db
from app.repositories.patient_repository import PatientRepository
from app.services.patient_service import PatientService

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: Annotated[str | None, Security(_api_key_header)]) -> None:
    """Reject the request unless `X-API-Key` matches `settings.API_KEY`, constant-time."""
    expected = get_settings().API_KEY.get_secret_value()
    if api_key is None or not secrets.compare_digest(api_key, expected):
        raise UnauthorizedError("Missing or invalid API key.")


def get_patient_service(session: Annotated[AsyncSession, Depends(get_db)]) -> PatientService:
    return PatientService(PatientRepository(session))
