"""create_call_logs

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-24 01:58:05.904527

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "call_logs",
        sa.Column(
            "call_log_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vapi_call_id", sa.Text(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=20), server_default="in_progress", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("ended_reason", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("recording_url", sa.Text(), nullable=True),
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
            "outcome IN ('registered', 'updated', 'abandoned', 'failed', 'in_progress', "
            "'no_action')",
            name=op.f("ck_call_logs_outcome_allowed_values"),
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name=op.f("ck_call_logs_duration_seconds_min"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.patient_id"],
            name=op.f("fk_call_logs_patient_id_patients"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("call_log_id", name=op.f("pk_call_logs")),
        sa.UniqueConstraint("vapi_call_id", name=op.f("uq_call_logs_vapi_call_id")),
    )
    op.create_index("ix_call_logs_created_at", "call_logs", ["created_at"], unique=False)
    op.create_index("ix_call_logs_patient_id", "call_logs", ["patient_id"], unique=False)

    # Reuse the same set_updated_at() function created in 0001 — only attach a new
    # trigger for this table.
    op.execute(
        """
        CREATE TRIGGER call_logs_set_updated_at
        BEFORE UPDATE ON call_logs
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS call_logs_set_updated_at ON call_logs")
    op.drop_index("ix_call_logs_patient_id", table_name="call_logs")
    op.drop_index("ix_call_logs_created_at", table_name="call_logs")
    op.drop_table("call_logs")
