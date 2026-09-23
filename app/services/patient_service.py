"""Business rules for patients — the only layer both REST and voice call into.

Both entry points validate input through the same `app/schemas/patient.py` models
(which themselves delegate to `app/validation/`), then call this service. Nothing here
is HTTP- or Vapi-specific.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.logging import mask_email, mask_name, mask_phone
from app.models.patient import Patient
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import PatientCreate, PatientUpdate

logger = logging.getLogger(__name__)


class PatientService:
    """Patient business rules: idempotent create, partial update, soft delete, lookups."""

    def __init__(self, repository: PatientRepository) -> None:
        self._repository = repository

    async def create_patient(
        self, data: PatientCreate, *, source_call_id: str | None = None
    ) -> tuple[Patient, bool]:
        """Create a patient. Returns `(patient, created)`.

        If `source_call_id` already has a patient, returns the existing record with
        `created=False` instead of inserting a duplicate — makes a retried voice "create"
        tool call idempotent (CLAUDE.md §8).
        """
        if source_call_id is not None:
            existing = await self._repository.get_by_source_call_id(source_call_id)
            if existing is not None:
                logger.info(
                    "patient create replayed (idempotent)",
                    extra={
                        "patient_id": str(existing.patient_id),
                        "source_call_id": source_call_id,
                    },
                )
                return existing, False

        fields = data.model_dump()
        fields["source_call_id"] = source_call_id
        patient = await self._repository.create(fields)
        logger.info(
            "patient created",
            extra={"patient_id": str(patient.patient_id), **self._masked_payload(patient)},
        )
        return patient, True

    async def update_patient(self, patient_id: uuid.UUID, data: PatientUpdate) -> Patient:
        """Partial update. Raises NotFoundError if missing or soft-deleted."""
        patient = await self.get_patient(patient_id)
        updated = await self._repository.update(patient, data.provided_fields())
        logger.info(
            "patient updated",
            extra={"patient_id": str(updated.patient_id), **self._masked_payload(updated)},
        )
        return updated

    async def delete_patient(self, patient_id: uuid.UUID) -> Patient:
        """Soft delete. Raises NotFoundError if missing or already deleted."""
        patient = await self.get_patient(patient_id)
        deleted = await self._repository.soft_delete(patient)
        logger.info("patient soft-deleted", extra={"patient_id": str(deleted.patient_id)})
        return deleted

    async def get_patient(self, patient_id: uuid.UUID) -> Patient:
        """Raises NotFoundError if missing or soft-deleted."""
        patient = await self._repository.get_by_id(patient_id)
        if patient is None:
            raise NotFoundError("Patient not found.")
        return patient

    async def list_patients(
        self,
        *,
        last_name: str | None = None,
        date_of_birth: date | None = None,
        phone_number: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Patient], int]:
        return await self._repository.list_patients(
            last_name=last_name,
            date_of_birth=date_of_birth,
            phone_number=phone_number,
            limit=limit,
            offset=offset,
        )

    async def find_by_phone(self, phone_number: str) -> list[Patient]:
        """Active (non-soft-deleted) matches only."""
        return await self._repository.find_active_by_phone(phone_number)

    async def verify_identity(self, patient_id: uuid.UUID, date_of_birth: date) -> bool:
        """Used before voice-initiated updates: does the caller know the DOB on file?"""
        patient = await self._repository.get_by_id(patient_id)
        if patient is None:
            return False
        return patient.date_of_birth == date_of_birth

    @staticmethod
    def _masked_payload(patient: Patient) -> dict[str, object]:
        """The final collected payload, PII masked unless LOG_PII=true (spec requirement:
        log the final collected data payload)."""
        log_pii = get_settings().LOG_PII
        return {
            "first_name": mask_name(patient.first_name, log_pii=log_pii),
            "last_name": mask_name(patient.last_name, log_pii=log_pii),
            "date_of_birth": patient.date_of_birth.isoformat(),
            "sex": patient.sex,
            "phone_number": mask_phone(patient.phone_number, log_pii=log_pii),
            "email": mask_email(patient.email, log_pii=log_pii) if patient.email else None,
            "city": patient.city,
            "state": patient.state,
            "zip_code": patient.zip_code,
            "preferred_language": patient.preferred_language,
            "has_insurance": patient.insurance_provider is not None,
            "has_emergency_contact": patient.emergency_contact_name is not None,
        }
