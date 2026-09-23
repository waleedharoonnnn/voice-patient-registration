"""Vapi tool handlers. NEVER raise — always return a short, speakable string.

Result-string prefixes below are a contract with the system prompt (documented in
docs/voice-tools.md): VALID/INVALID, NO_MATCH/MATCH, SAVED/ALREADY_SAVED/SAVE_FAILED,
UPDATED/IDENTITY_MISMATCH/NOT_FOUND, SLOTS/NO_SLOTS, BOOKED/SLOT_TAKEN/BOOK_FAILED.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services.appointment_service import AppointmentService
from app.services.call_log_service import CallLogService
from app.services.patient_service import PatientService
from app.validation.dates import parse_calendar_date, parse_dob
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
SLOTS = "SLOTS"
NO_SLOTS = "NO_SLOTS"
BOOKED = "BOOKED"
SLOT_TAKEN = "SLOT_TAKEN"
BOOK_FAILED = "BOOK_FAILED"


@dataclass
class ToolContext:
    """Everything a tool handler needs, bundled so signatures don't grow per tool."""

    call_id: str
    patient_service: PatientService
    call_log_service: CallLogService
    appointment_service: AppointmentService


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"]) or "value"
        message = str(error["msg"]).removeprefix("Value error, ")
        parts.append(f"{field}: {message}")
    return f"{INVALID}: " + "; ".join(parts)


async def _safe_record_progress(
    ctx: ToolContext, call_id: str, *, patient_id: uuid.UUID | None, outcome: str
) -> None:
    """Call-log bookkeeping must never change what the caller hears — log and move on."""
    try:
        await ctx.call_log_service.record_progress(call_id, patient_id=patient_id, outcome=outcome)
    except Exception:
        logger.exception("call log update failed", extra={"call_id": call_id})


async def validate_fields(arguments: ToolArguments, ctx: ToolContext) -> str:
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


async def find_patient_by_phone(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Only name + id are ever returned — never other PII."""
    try:
        phone = normalize_us_phone(
            str(arguments.get("phone_number", "")), field_name="Phone number"
        )
    except ValueError as exc:
        return f"{INVALID}: phone_number: {exc}"

    matches = await ctx.patient_service.find_by_phone(phone)
    if not matches:
        return NO_MATCH
    rendered = "; ".join(
        f"patient_id={p.patient_id}; first_name={p.first_name}; last_name={p.last_name}"
        for p in matches[:3]
    )
    return f"{MATCH}: {rendered}"


async def create_patient(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Uses the call id as source_call_id: a retried call returns ALREADY_SAVED, not a dup."""
    try:
        data = PatientCreate.model_validate(arguments)
    except ValidationError as exc:
        return _format_validation_error(exc)

    try:
        patient, created = await ctx.patient_service.create_patient(
            data, source_call_id=ctx.call_id
        )
    except Exception:
        logger.exception("create_patient tool failed", extra={"call_id": ctx.call_id})
        await _safe_record_progress(ctx, ctx.call_id, patient_id=None, outcome="failed")
        return f"{SAVE_FAILED}: I'm having trouble saving right now."

    await _safe_record_progress(
        ctx, ctx.call_id, patient_id=patient.patient_id, outcome="registered"
    )
    prefix = SAVED if created else ALREADY_SAVED
    return f"{prefix}: patient_id={patient.patient_id}; first_name={patient.first_name}"


async def update_patient(arguments: ToolArguments, ctx: ToolContext) -> str:
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

    if not await ctx.patient_service.verify_identity(patient_id, dob):
        try:
            await ctx.patient_service.get_patient(patient_id)
        except NotFoundError:
            return NOT_FOUND
        return IDENTITY_MISMATCH

    fields = arguments.get("fields")
    try:
        update_data = PatientUpdate.model_validate(fields if isinstance(fields, dict) else {})
    except ValidationError as exc:
        return _format_validation_error(exc)

    try:
        patient = await ctx.patient_service.update_patient(patient_id, update_data)
    except NotFoundError:
        return NOT_FOUND
    except Exception:
        logger.exception("update_patient tool failed", extra={"call_id": ctx.call_id})
        await _safe_record_progress(ctx, ctx.call_id, patient_id=patient_id, outcome="failed")
        return f"{SAVE_FAILED}: I'm having trouble saving right now."

    await _safe_record_progress(ctx, ctx.call_id, patient_id=patient.patient_id, outcome="updated")
    return f"{UPDATED}: patient_id={patient.patient_id}; first_name={patient.first_name}"


def _speak_time(dt: datetime) -> str:
    """'Tuesday, October 6 at 10:30 AM', in the clinic's local timezone."""
    tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
    local = dt.astimezone(tz)
    return local.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


async def get_available_slots(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Up to 3 options across all active providers."""
    preferred_date: date | None = None
    raw_date = arguments.get("preferred_date")
    if raw_date:
        try:
            preferred_date = parse_calendar_date(str(raw_date), field_name="Preferred date")
        except ValueError as exc:
            return f"{INVALID}: preferred_date: {exc}"

    time_of_day = arguments.get("time_of_day")
    if time_of_day not in (None, "morning", "afternoon", "any"):
        return f"{INVALID}: time_of_day: must be 'morning', 'afternoon', or 'any'."

    slots = await ctx.appointment_service.get_available_slots(
        preferred_date=preferred_date,
        time_of_day=None if time_of_day == "any" else time_of_day,
    )
    if not slots:
        return NO_SLOTS

    rendered = "; ".join(
        f"{i}) {slot.slot_id} | {_speak_time(slot.start_time)} Eastern with {slot.provider_name}"
        for i, slot in enumerate(slots, start=1)
    )
    return f"{SLOTS}: {rendered}"


async def book_appointment(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Idempotent per call: a retried booking for the same call returns the same result."""
    try:
        patient_id = uuid.UUID(str(arguments.get("patient_id")))
    except (ValueError, TypeError, AttributeError):
        return f"{INVALID}: patient_id: Not a valid patient id."

    slot_id = arguments.get("slot_id")
    if not slot_id or not isinstance(slot_id, str):
        return f"{INVALID}: slot_id: A slot id is required."

    reason = arguments.get("reason")
    reason_str = str(reason).strip()[:200] if reason else None

    try:
        appointment = await ctx.appointment_service.book_appointment(
            patient_id=patient_id,
            slot_id=slot_id,
            reason=reason_str,
            source_call_id=ctx.call_id,
        )
    except ValueError as exc:
        return f"{INVALID}: slot_id: {exc}"
    except ValidationFailedError as exc:
        return f"{INVALID}: {exc.message}"
    except ConflictError:
        return SLOT_TAKEN
    except Exception:
        logger.exception("book_appointment tool failed", extra={"call_id": ctx.call_id})
        return f"{BOOK_FAILED}: I'm having trouble booking that right now."

    spoken_time = _speak_time(appointment.start_time)
    return f"{BOOKED}: appointment_id={appointment.appointment_id}; time={spoken_time} Eastern"


TOOL_HANDLERS = {
    "validate_fields": validate_fields,
    "find_patient_by_phone": find_patient_by_phone,
    "create_patient": create_patient,
    "update_patient": update_patient,
    "get_available_slots": get_available_slots,
    "book_appointment": book_appointment,
}
