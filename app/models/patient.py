"""The `patients` table.

Column lengths and CHECK constraints mirror the rules in `app/validation/` (defense in
depth — see docs/adr/0003-patient-schema.md). This module declares tables only; no
business logic.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.validation.address import US_STATES
from app.validation.demographics import DEFAULT_LANGUAGE, SEX_VALUES

_STATE_LIST_SQL = ", ".join(f"'{code}'" for code in sorted(US_STATES))
_SEX_LIST_SQL = ", ".join(f"'{value}'" for value in SEX_VALUES)

# NANP: area code and exchange (first digit of each 3-digit group) must be 2-9.
_PHONE_PATTERN = r"^[2-9]\d{2}[2-9]\d{6}$"
_ZIP_PATTERN = r"^\d{5}(-\d{4})?$"
# Matches app.validation.names' pattern. The literal apostrophe in the character class is
# doubled ('') because this string is embedded verbatim in a single-quoted SQL literal.
_NAME_PATTERN = r"^[^\W\d_]+([ ''\-][^\W\d_]+)*$"


class Patient(Base):
    """A patient demographic record collected by the voice agent or the REST API."""

    __tablename__ = "patients"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(nullable=False)
    sex: Mapped[str] = mapped_column(String(20), nullable=False)

    phone_number: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    address_line_1: Mapped[str] = mapped_column(String(100), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)

    preferred_language: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=DEFAULT_LANGUAGE
    )

    emergency_contact_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10), nullable=True)

    insurance_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    insurance_member_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Vapi call.id; stored to make voice-initiated "create" tool calls idempotent on retry.
    source_call_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"first_name ~ '{_NAME_PATTERN}'", name="first_name_format"),
        CheckConstraint(f"last_name ~ '{_NAME_PATTERN}'", name="last_name_format"),
        CheckConstraint(
            f"emergency_contact_name IS NULL OR emergency_contact_name ~ '{_NAME_PATTERN}'",
            name="emergency_contact_name_format",
        ),
        CheckConstraint(f"sex IN ({_SEX_LIST_SQL})", name="sex_allowed_values"),
        CheckConstraint(f"phone_number ~ '{_PHONE_PATTERN}'", name="phone_number_format"),
        CheckConstraint(
            f"emergency_contact_phone IS NULL OR emergency_contact_phone ~ '{_PHONE_PATTERN}'",
            name="emergency_contact_phone_format",
        ),
        CheckConstraint(f"state IN ({_STATE_LIST_SQL})", name="state_allowed_values"),
        CheckConstraint(f"zip_code ~ '{_ZIP_PATTERN}'", name="zip_code_format"),
        CheckConstraint("date_of_birth >= '1900-01-01'", name="date_of_birth_min"),
        CheckConstraint("length(trim(first_name)) >= 1", name="first_name_length"),
        CheckConstraint("length(trim(last_name)) >= 1", name="last_name_length"),
        CheckConstraint("length(trim(address_line_1)) >= 1", name="address_line_1_length"),
        CheckConstraint("length(trim(city)) >= 1", name="city_length"),
        Index("ix_patients_last_name_lower", text("lower(last_name)")),
        Index("ix_patients_date_of_birth", "date_of_birth"),
        # Phone is intentionally NOT unique (families share a number); this partial index
        # only speeds up duplicate-detection lookups among non-deleted rows.
        Index(
            "ix_patients_phone_number_active",
            "phone_number",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
