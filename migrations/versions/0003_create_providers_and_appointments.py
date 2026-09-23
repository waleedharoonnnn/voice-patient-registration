"""create_providers_and_appointments

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24 01:58:59.753548

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed IDs so they're stable/referenceable across environments, same convention as the
# seed patients in scripts/seed.py.
_PROVIDERS = (
    ("10000000-0000-0000-0000-000000000001", "Dr. Amara Okafor", "Family Medicine"),
    ("10000000-0000-0000-0000-000000000002", "Dr. Ben Whitfield", "Internal Medicine"),
    ("10000000-0000-0000-0000-000000000003", "Dr. Priya Nataraj", "Pediatrics"),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "providers",
        sa.Column(
            "provider_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("specialty", sa.String(length=100), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("provider_id", name=op.f("pk_providers")),
    )
    op.create_table(
        "appointments",
        sa.Column(
            "appointment_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("provider_id", sa.UUID(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), server_default=sa.text("30"), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="booked", nullable=False),
        sa.Column("source_call_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('booked', 'cancelled')", name=op.f("ck_appointments_status_allowed_values")
        ),
        sa.CheckConstraint(
            "duration_minutes > 0", name=op.f("ck_appointments_duration_minutes_positive")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.patient_id"],
            name=op.f("fk_appointments_patient_id_patients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.provider_id"],
            name=op.f("fk_appointments_provider_id_providers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("appointment_id", name=op.f("pk_appointments")),
    )
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"], unique=False)
    op.create_index(
        "ux_appointments_provider_start_time_booked",
        "appointments",
        ["provider_id", "start_time"],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )

    op.execute(
        """
        CREATE TRIGGER appointments_set_updated_at
        BEFORE UPDATE ON appointments
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )

    providers_table = sa.table(
        "providers",
        sa.column("provider_id", sa.UUID()),
        sa.column("full_name", sa.String()),
        sa.column("specialty", sa.String()),
    )
    op.bulk_insert(
        providers_table,
        [
            {"provider_id": provider_id, "full_name": full_name, "specialty": specialty}
            for provider_id, full_name, specialty in _PROVIDERS
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS appointments_set_updated_at ON appointments")
    op.drop_index(
        "ux_appointments_provider_start_time_booked",
        table_name="appointments",
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.drop_index("ix_appointments_patient_id", table_name="appointments")
    op.drop_table("appointments")
    op.drop_table("providers")
