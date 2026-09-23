"""Mock appointment scheduling: computed availability + booking.

Availability is never stored — it's computed from clinic business hours minus already
`booked` rows. See docs/adr/0008-mock-appointment-scheduling.md.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.models.appointment import Appointment
from app.models.provider import Provider
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.provider_repository import ProviderRepository
from app.services.slots import decode_slot_id, encode_slot_id

BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 17
SLOT_MINUTES = 30
AVAILABILITY_WINDOW_DAYS = 14


@dataclass(frozen=True)
class AvailableSlot:
    slot_id: str
    provider_id: uuid.UUID
    provider_name: str
    start_time: datetime  # tz-aware, in the clinic timezone


def _business_slots(day: datetime) -> Iterator[datetime]:
    current = day.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
    end = day.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
    while current < end:
        yield current
        current += timedelta(minutes=SLOT_MINUTES)


def _matches_time_of_day(slot_start: datetime, time_of_day: str | None) -> bool:
    if time_of_day == "morning":
        return slot_start.hour < 12
    if time_of_day == "afternoon":
        return slot_start.hour >= 12
    return True  # None or "any"


class AppointmentService:
    def __init__(
        self,
        appointment_repository: AppointmentRepository,
        provider_repository: ProviderRepository,
    ) -> None:
        self._appointments = appointment_repository
        self._providers = provider_repository

    async def get_available_slots(
        self,
        *,
        preferred_date: date | None = None,
        time_of_day: str | None = None,
        limit: int = 3,
    ) -> list[AvailableSlot]:
        """Mon-Fri, business hours, from tomorrow through the next 14 days."""
        tz = ZoneInfo(get_settings().CLINIC_TIMEZONE)
        now = datetime.now(tz)
        window_start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = window_start + timedelta(days=AVAILABILITY_WINDOW_DAYS)

        providers = await self._providers.list_active()
        if not providers:
            return []

        booked = await self._appointments.list_booked_start_times(
            [p.provider_id for p in providers],
            start=window_start.astimezone(UTC),
            end=window_end.astimezone(UTC),
        )

        candidates: list[AvailableSlot] = []
        day = window_start
        while day < window_end:
            is_weekday = day.weekday() < 5
            matches_preferred_date = preferred_date is None or day.date() == preferred_date
            if is_weekday and matches_preferred_date:
                for slot_start in _business_slots(day):
                    if _matches_time_of_day(slot_start, time_of_day):
                        for provider in providers:
                            key = (provider.provider_id, slot_start.astimezone(UTC))
                            if key not in booked:
                                candidates.append(
                                    AvailableSlot(
                                        slot_id=encode_slot_id(provider.provider_id, slot_start),
                                        provider_id=provider.provider_id,
                                        provider_name=provider.full_name,
                                        start_time=slot_start,
                                    )
                                )
            day += timedelta(days=1)

        candidates.sort(key=lambda slot: slot.start_time)
        return candidates[:limit]

    async def book_appointment(
        self,
        *,
        patient_id: uuid.UUID,
        slot_id: str,
        reason: str | None,
        source_call_id: str | None,
    ) -> Appointment:
        """Raises ValueError (bad/expired slot), ConflictError (SLOT_TAKEN via the DB's
        unique index), or ValidationFailedError (unknown/inactive provider)."""
        if source_call_id is not None:
            existing = await self._appointments.get_by_source_call_id(source_call_id)
            if existing is not None:
                return existing

        provider_id, start_time = decode_slot_id(slot_id)

        provider = await self._providers.get_by_id(provider_id)
        if provider is None or not provider.active:
            raise ValidationFailedError("That provider is no longer available.")

        fields: dict[str, object] = {
            "patient_id": patient_id,
            "provider_id": provider_id,
            "start_time": start_time,
            "reason": reason,
            "source_call_id": source_call_id,
        }
        return await self._appointments.create(fields)

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[Appointment]:
        return await self._appointments.list_for_patient(patient_id)

    async def list_providers(self) -> list[Provider]:
        return await self._providers.list_active()

    async def count_upcoming(self) -> int:
        return await self._appointments.count_upcoming(datetime.now(UTC))
