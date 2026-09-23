"""The `call_logs` table — one row per Vapi call, linked to a patient when known.

See docs/adr/0007-call-logs-and-transcripts.md for why this exists and how it's
populated (from tool-call outcomes and the end-of-call-report webhook message).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

OUTCOMES: tuple[str, ...] = (
    "registered",
    "updated",
    "abandoned",
    "failed",
    "in_progress",
    "no_action",
)
_OUTCOME_LIST_SQL = ", ".join(f"'{value}'" for value in OUTCOMES)


class CallLog(Base):
    """A single phone/web call to the voice agent."""

    __tablename__ = "call_logs"

    call_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    vapi_call_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="SET NULL"),
        nullable=True,
    )

    outcome: Mapped[str] = mapped_column(String(20), nullable=False, server_default="in_progress")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(f"outcome IN ({_OUTCOME_LIST_SQL})", name="outcome_allowed_values"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="duration_seconds_min"
        ),
        Index("ix_call_logs_patient_id", "patient_id"),
        Index("ix_call_logs_created_at", "created_at"),
    )
