"""Vapi tool handlers. NEVER raise — always return a short, speakable string.

Result-string prefixes below are a contract with the system prompt (documented in
docs/voice-tools.md): VALID/INVALID, NO_MATCH/MATCH, SAVED/ALREADY_SAVED/SAVE_FAILED,
UPDATED/IDENTITY_MISMATCH/NOT_FOUND, SLOTS/NO_SLOTS, BOOKED/SLOT_TAKEN/BOOK_FAILED,
NO_CALLER_ID/CALLER_ON_FILE/VERIFIED, CANCELLED/CANCEL_FAILED, RESCHEDULED/RESCHEDULE_FAILED.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.patient import Patient
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
NO_CALLER_ID = "NO_CALLER_ID"
CALLER_ON_FILE = "CALLER_ON_FILE"
VERIFIED = "VERIFIED"
CANCELLED = "CANCELLED"
CANCEL_FAILED = "CANCEL_FAILED"
RESCHEDULED = "RESCHEDULED"
RESCHEDULE_FAILED = "RESCHEDULE_FAILED"

_DR_TITLE_RE = re.compile(r"\bDr\.?(?=\s)")


@dataclass
class ToolContext:
    """Everything a tool handler needs, bundled so signatures don't grow per tool."""

    call_id: str
    patient_service: PatientService
    call_log_service: CallLogService
    appointment_service: AppointmentService
    # Caller ID as Vapi sent it (E.164); None on web calls or withheld numbers.
    caller_number: str | None = None


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
    """Requires date_of_birth to match the stored record before applying `fields`, unless
    the record was created earlier in this call (a post-save correction)."""
    try:
        patient_id = uuid.UUID(str(arguments.get("patient_id")))
    except (ValueError, TypeError, AttributeError):
        return NOT_FOUND

    # A record saved earlier in this same call needs no second DOB check: the caller just
    # confirmed every field. Any other record must prove identity with the DOB on file.
    if not await ctx.patient_service.was_created_by_call(patient_id, ctx.call_id):
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


def _caller_phone(ctx: ToolContext) -> str | None:
    """The caller ID as a normalized US number, or None if absent or not a US number."""
    if not ctx.caller_number:
        return None
    try:
        return normalize_us_phone(ctx.caller_number, field_name="Caller ID")
    except ValueError:
        return None


async def identify_caller(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Is the caller ID on file? Deliberately reveals NO name or details: caller ID can be
    spoofed or shared, so nothing is disclosed until `verify_caller` checks the DOB.

    Returns the caller's own normalized number (`caller_phone`) so the agent can offer it
    as their phone number and read it back, instead of asking for it.
    """
    phone = _caller_phone(ctx)
    if phone is None:
        return NO_CALLER_ID
    if not await ctx.patient_service.find_by_phone(phone):
        return f"{NO_MATCH}: caller_phone={phone}"
    return f"{CALLER_ON_FILE}: caller_phone={phone}"


def _identity_phone(arguments: ToolArguments, ctx: ToolContext) -> str:
    """The phone that identifies the caller: a stated `phone_number`, else the caller ID.

    Raises ValueError (stated number invalid) or LookupError (no number at all).
    """
    raw = arguments.get("phone_number")
    if raw:
        return normalize_us_phone(str(raw), field_name="Phone number")
    phone = _caller_phone(ctx)
    if phone is None:
        raise LookupError("no caller phone")
    return phone


async def _verified_patients(arguments: ToolArguments, ctx: ToolContext) -> list[Patient] | str:
    """Patients matching phone + stated DOB, or the result string to return instead."""
    try:
        phone = _identity_phone(arguments, ctx)
    except LookupError:
        return NO_CALLER_ID
    except ValueError as exc:
        return f"{INVALID}: phone_number: {exc}"

    raw_dob = arguments.get("date_of_birth")
    if not raw_dob:
        return f"{INVALID}: date_of_birth: Date of birth is required to verify identity."
    try:
        dob = parse_dob(str(raw_dob))
    except ValueError as exc:
        return f"{INVALID}: date_of_birth: {exc}"

    patients = await ctx.patient_service.find_all_verified_by_phone(phone, dob)
    return patients or IDENTITY_MISMATCH


async def verify_caller(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Phone (stated, else caller ID) + stated DOB → the patient's first name, id, and
    upcoming appointments (with ids, for cancel/reschedule)."""
    verified = await _verified_patients(arguments, ctx)
    if isinstance(verified, str):
        return verified
    patient = verified[0]

    upcoming = await ctx.appointment_service.upcoming_for_patient(patient.patient_id)
    rendered = (
        " | ".join(
            f"appointment_id={appt.appointment_id}, {_speak_time(appt.start_time)} Eastern "
            f"with {_speak_provider(provider)}"
            for appt, provider in upcoming
        )
        or "none"
    )
    return (
        f"{VERIFIED}: patient_id={patient.patient_id}; first_name={patient.first_name}; "
        f"upcoming_appointments={rendered}"
    )


def _speak_provider(name: str) -> str:
    """'Dr. Amara Okafor' -> 'Doctor Amara Okafor': TTS can misread the abbreviation."""
    return _DR_TITLE_RE.sub("Doctor", name)


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
        f"{i}) {slot.slot_id} | {_speak_time(slot.start_time)} Eastern with "
        f"{_speak_provider(slot.provider_name)}"
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


def _appointment_id(arguments: ToolArguments) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(arguments.get("appointment_id")))
    except (ValueError, TypeError, AttributeError):
        return None


async def cancel_appointment(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Cancel the caller's own upcoming appointment, after phone + DOB verification."""
    verified = await _verified_patients(arguments, ctx)
    if isinstance(verified, str):
        return verified
    appointment_id = _appointment_id(arguments)
    if appointment_id is None:
        return NOT_FOUND

    try:
        appointment, provider = await ctx.appointment_service.cancel_appointment(
            appointment_id=appointment_id, patient_ids=[p.patient_id for p in verified]
        )
    except NotFoundError:
        return NOT_FOUND
    except Exception:
        logger.exception("cancel_appointment tool failed", extra={"call_id": ctx.call_id})
        return f"{CANCEL_FAILED}: I'm having trouble cancelling that right now."

    return (
        f"{CANCELLED}: appointment_id={appointment.appointment_id}; "
        f"time={_speak_time(appointment.start_time)} Eastern with {_speak_provider(provider)}"
    )


async def reschedule_appointment(arguments: ToolArguments, ctx: ToolContext) -> str:
    """Move the caller's own booked appointment to a slot from get_available_slots."""
    verified = await _verified_patients(arguments, ctx)
    if isinstance(verified, str):
        return verified
    appointment_id = _appointment_id(arguments)
    if appointment_id is None:
        return NOT_FOUND
    slot_id = arguments.get("slot_id")
    if not slot_id or not isinstance(slot_id, str):
        return f"{INVALID}: slot_id: A slot id is required."

    try:
        appointment, provider = await ctx.appointment_service.reschedule_appointment(
            appointment_id=appointment_id,
            patient_ids=[p.patient_id for p in verified],
            slot_id=slot_id,
        )
    except NotFoundError:
        return NOT_FOUND
    except ValueError as exc:
        return f"{INVALID}: slot_id: {exc}"
    except ValidationFailedError as exc:
        return f"{INVALID}: {exc.message}"
    except ConflictError:
        return SLOT_TAKEN
    except Exception:
        logger.exception("reschedule_appointment tool failed", extra={"call_id": ctx.call_id})
        return f"{RESCHEDULE_FAILED}: I'm having trouble rescheduling that right now."

    return (
        f"{RESCHEDULED}: appointment_id={appointment.appointment_id}; "
        f"time={_speak_time(appointment.start_time)} Eastern with {_speak_provider(provider)}"
    )


TOOL_HANDLERS = {
    "identify_caller": identify_caller,
    "verify_caller": verify_caller,
    "validate_fields": validate_fields,
    "find_patient_by_phone": find_patient_by_phone,
    "create_patient": create_patient,
    "update_patient": update_patient,
    "get_available_slots": get_available_slots,
    "book_appointment": book_appointment,
    "cancel_appointment": cancel_appointment,
    "reschedule_appointment": reschedule_appointment,
}
