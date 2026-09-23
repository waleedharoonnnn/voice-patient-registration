"""The `providers` table — a small, fixed set of fake clinicians for mock scheduling.

Seeded in the migration itself, not scripts/seed.py — see
docs/adr/0008-mock-appointment-scheduling.md for why.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Provider(Base):
    """A clinician appointments can be booked with."""

    __tablename__ = "providers"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    specialty: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
