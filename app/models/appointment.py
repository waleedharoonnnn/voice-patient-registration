"""The `appointments` table.

Double-booking is prevented by the database, not the app: a partial unique index on
`(provider_id, start_time) WHERE status = 'booked'` means two concurrent booking
attempts for the same slot can't both succeed, regardless of any race in application
code. See docs/adr/0008-mock-appointment-scheduling.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUSES: tuple[str, ...] = ("booked", "cancelled")
_STATUS_LIST_SQL = ", ".join(f"'{value}'" for value in STATUSES)


class Appointment(Base):
    """A booked (or cancelled) slot with a provider."""

    __tablename__ = "appointments"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("providers.provider_id", ondelete="RESTRICT"),
        nullable=False,
    )

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(nullable=False, server_default=text("30"))
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="booked")

    # Vapi call.id; lets a retried book_appointment tool call be idempotent.
    source_call_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST_SQL})", name="status_allowed_values"),
        CheckConstraint("duration_minutes > 0", name="duration_minutes_positive"),
        Index("ix_appointments_patient_id", "patient_id"),
        # The actual double-booking guard: two 'booked' rows can never share a
        # (provider, start_time). Cancelled rows don't count, so the slot frees up again.
        Index(
            "ux_appointments_provider_start_time_booked",
            "provider_id",
            "start_time",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
    )
