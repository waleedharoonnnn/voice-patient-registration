"""`/patients` REST endpoints. Thin: parses/validates, delegates to PatientService."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_patient_service, require_api_key
from app.core.errors import NotFoundError, ValidationFailedError
from app.schemas.common import Envelope
from app.schemas.patient import (
    PatientCreate,
    PatientListOut,
    PatientListQuery,
    PatientOut,
    PatientUpdate,
)
from app.services.patient_service import PatientService
from app.validation.dates import parse_dob

router = APIRouter(
    prefix="/patients",
    tags=["patients"],
    dependencies=[Depends(require_api_key)],
)


def _parse_patient_id(raw: str) -> uuid.UUID:
    """Malformed UUID in the path is a 404, not a 422 or 500 (CLAUDE.md §4)."""
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise NotFoundError("Patient not found.") from exc


@router.get(
    "",
    summary="List patients",
    description="Optional filters: last_name (case-insensitive exact), date_of_birth, "
    "phone_number. Paginated with limit/offset.",
)
async def list_patients(
    filters: Annotated[PatientListQuery, Depends()],
    service: Annotated[PatientService, Depends(get_patient_service)],
) -> Envelope[PatientListOut]:
    date_of_birth = None
    if filters.date_of_birth:
        try:
            date_of_birth = parse_dob(filters.date_of_birth)
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc

    patients, total = await service.list_patients(
        last_name=filters.last_name,
        date_of_birth=date_of_birth,
        phone_number=filters.phone_number,
        limit=filters.limit,
        offset=filters.offset,
    )
    data = PatientListOut(
        items=[PatientOut.model_validate(p) for p in patients],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )
    return Envelope(data=data)


@router.get("/{patient_id}", summary="Get a patient by ID")
async def get_patient(
    patient_id: str,
    service: Annotated[PatientService, Depends(get_patient_service)],
) -> Envelope[PatientOut]:
    patient = await service.get_patient(_parse_patient_id(patient_id))
    return Envelope(data=PatientOut.model_validate(patient))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a patient",
)
async def create_patient(
    body: PatientCreate,
    service: Annotated[PatientService, Depends(get_patient_service)],
) -> Envelope[PatientOut]:
    patient, _created = await service.create_patient(body)
    return Envelope(data=PatientOut.model_validate(patient))


@router.put("/{patient_id}", summary="Partially update a patient")
async def update_patient(
    patient_id: str,
    body: PatientUpdate,
    service: Annotated[PatientService, Depends(get_patient_service)],
) -> Envelope[PatientOut]:
    patient = await service.update_patient(_parse_patient_id(patient_id), body)
    return Envelope(data=PatientOut.model_validate(patient))


@router.delete("/{patient_id}", summary="Soft-delete a patient")
async def delete_patient(
    patient_id: str,
    service: Annotated[PatientService, Depends(get_patient_service)],
) -> Envelope[PatientOut]:
    patient = await service.delete_patient(_parse_patient_id(patient_id))
    return Envelope(data=PatientOut.model_validate(patient))
