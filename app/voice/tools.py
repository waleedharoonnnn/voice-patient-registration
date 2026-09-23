"""Vapi tool handlers. NEVER raise — always return a short, speakable string.

Result-string prefixes below are a contract with the system prompt (documented in
docs/voice-tools.md): VALID/INVALID, NO_MATCH/MATCH, SAVED/ALREADY_SAVED/SAVE_FAILED,
UPDATED/IDENTITY_MISMATCH/NOT_FOUND.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import ValidationError

from app.core.errors import NotFoundError
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services.patient_service import PatientService
from app.validation.dates import parse_dob
from app.validation.phone import normalize_us_phone

logger = logging.getLogger(__name__)

ToolArguments = dict[str, Any]

VALID = "VALID"
INVALID = "INVALID"
NO_MATCH = "NO_MATCH"
MATCH = "MATCH"
SAVED = "SAVED"
ALREADY_SAVED = "ALREADY_SAVED"
SAVE_FAILED = "SAVE_FAILED"
UPDATED = "UPDATED"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
NOT_FOUND = "NOT_FOUND"


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"]) or "value"
        message = str(error["msg"]).removeprefix("Value error, ")
        parts.append(f"{field}: {message}")
    return f"{INVALID}: " + "; ".join(parts)


async def validate_fields(
    arguments: ToolArguments, *, call_id: str, service: PatientService
) -> str:
    """Validate any subset of patient fields with the same validators the REST API uses."""
    fields = arguments.get("fields")
    try:
        model = PatientUpdate.model_validate(fields if isinstance(fields, dict) else {})
    except ValidationError as exc:
        return _format_validation_error(exc)
    normalized = model.provided_fields()
    if not normalized:
        return f"{VALID}: (no fields provided)"
    rendered = "; ".join(f"{key}={value}" for key, value in normalized.items())
    return f"{VALID}: {rendered}"


async def find_patient_by_phone(
    arguments: ToolArguments, *, call_id: str, service: PatientService
) -> str:
    """Only name + id are ever returned — never other PII."""
    try:
        phone = normalize_us_phone(
            str(arguments.get("phone_number", "")), field_name="Phone number"
        )
    except ValueError as exc:
        return f"{INVALID}: phone_number: {exc}"

    matches = await service.find_by_phone(phone)
    if not matches:
        return NO_MATCH
    rendered = "; ".join(
        f"patient_id={p.patient_id}; first_name={p.first_name}; last_name={p.last_name}"
        for p in matches[:3]
    )
    return f"{MATCH}: {rendered}"


async def create_patient(arguments: ToolArguments, *, call_id: str, service: PatientService) -> str:
    """Uses the call id as source_call_id: a retried call returns ALREADY_SAVED, not a dup."""
    try:
        data = PatientCreate.model_validate(arguments)
    except ValidationError as exc:
        return _format_validation_error(exc)

    try:
        patient, created = await service.create_patient(data, source_call_id=call_id)
    except Exception:
        logger.exception("create_patient tool failed", extra={"call_id": call_id})
        return f"{SAVE_FAILED}: I'm having trouble saving right now."

    prefix = SAVED if created else ALREADY_SAVED
    return f"{prefix}: patient_id={patient.patient_id}; first_name={patient.first_name}"


async def update_patient(arguments: ToolArguments, *, call_id: str, service: PatientService) -> str:
    """Requires date_of_birth to match the stored record before applying `fields`."""
    try:
        patient_id = uuid.UUID(str(arguments.get("patient_id")))
    except (ValueError, TypeError, AttributeError):
        return NOT_FOUND

    raw_dob = arguments.get("date_of_birth")
    if not raw_dob:
        return f"{INVALID}: date_of_birth: Date of birth is required to verify identity."
    try:
        dob = parse_dob(str(raw_dob))
    except ValueError as exc:
        return f"{INVALID}: date_of_birth: {exc}"

    if not await service.verify_identity(patient_id, dob):
        try:
            await service.get_patient(patient_id)
        except NotFoundError:
            return NOT_FOUND
        return IDENTITY_MISMATCH

    fields = arguments.get("fields")
    try:
        update_data = PatientUpdate.model_validate(fields if isinstance(fields, dict) else {})
    except ValidationError as exc:
        return _format_validation_error(exc)

    try:
        patient = await service.update_patient(patient_id, update_data)
    except NotFoundError:
        return NOT_FOUND
    except Exception:
        logger.exception("update_patient tool failed", extra={"call_id": call_id})
        return f"{SAVE_FAILED}: I'm having trouble saving right now."

    return f"{UPDATED}: patient_id={patient.patient_id}; first_name={patient.first_name}"


TOOL_HANDLERS = {
    "validate_fields": validate_fields,
    "find_patient_by_phone": find_patient_by_phone,
    "create_patient": create_patient,
    "update_patient": update_patient,
}
