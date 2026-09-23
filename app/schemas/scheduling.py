"""Response models for call logs, appointments, and providers (read-only endpoints)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_id: UUID
    full_name: str
    specialty: str
    active: bool


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    appointment_id: UUID
    patient_id: UUID
    provider_id: UUID
    start_time: datetime
    duration_minutes: int
    reason: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CallLogOut(BaseModel):
    """Includes the full transcript: staff following up on an abandoned call need it."""

    model_config = ConfigDict(from_attributes=True)

    call_log_id: UUID
    vapi_call_id: str
    patient_id: UUID | None
    outcome: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    ended_reason: str | None
    language: str | None
    summary: str | None
    transcript: str | None
    recording_url: str | None
    created_at: datetime
    updated_at: datetime
