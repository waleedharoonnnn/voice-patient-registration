"""DB access for appointments.

The double-booking guard is the database's partial unique index
(`ux_appointments_provider_start_time_booked`), not application logic — `create` here
just translates the resulting `IntegrityError` into a domain `ConflictError`. See
docs/adr/0008-mock-appointment-scheduling.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.models.appointment import Appointment


class AppointmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_source_call_id(self, source_call_id: str) -> Appointment | None:
        stmt = select(Appointment).where(Appointment.source_call_id == source_call_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_booked_start_times(
        self, provider_ids: list[uuid.UUID], *, start: datetime, end: datetime
    ) -> set[tuple[uuid.UUID, datetime]]:
        """Booked (provider_id, start_time) pairs in [start, end) — used to exclude slots."""
        stmt = select(Appointment.provider_id, Appointment.start_time).where(
            Appointment.provider_id.in_(provider_ids),
            Appointment.status == "booked",
            Appointment.start_time >= start,
            Appointment.start_time < end,
        )
        result = await self._session.execute(stmt)
        return {(row.provider_id, row.start_time) for row in result.all()}

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[Appointment]:
        stmt = (
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .order_by(Appointment.start_time.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_upcoming(self, now: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.status == "booked", Appointment.start_time >= now)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def create(self, fields: dict[str, object]) -> Appointment:
        appointment = Appointment(**fields)
        try:
            # Savepoint: a constraint failure rolls back only this insert, leaving the
            # request's transaction usable (the caller still gets a clean result).
            async with self._session.begin_nested():
                self._session.add(appointment)
                await self._session.flush()
        except IntegrityError as exc:
            detail = str(exc.orig).lower() if exc.orig else ""
            if "ux_appointments_provider_start_time_booked" in detail or "unique" in detail:
                raise ConflictError("That slot was just booked by someone else.") from exc
            raise
        await self._session.refresh(appointment)
        return appointment
