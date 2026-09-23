"""create_patients

Revision ID: 0001
Revises:
Create Date: 2026-09-24 00:02:24.697820

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "patients",
        sa.Column(
            "patient_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(length=50), nullable=False),
        sa.Column("last_name", sa.String(length=50), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("sex", sa.String(length=20), nullable=False),
        sa.Column("phone_number", sa.String(length=10), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("address_line_1", sa.String(length=100), nullable=False),
        sa.Column("address_line_2", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column("zip_code", sa.String(length=10), nullable=False),
        sa.Column(
            "preferred_language",
            sa.String(length=50),
            server_default="English",
            nullable=False,
        ),
        sa.Column("emergency_contact_name", sa.String(length=50), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(length=10), nullable=True),
        sa.Column("insurance_provider", sa.String(length=100), nullable=True),
        sa.Column("insurance_member_id", sa.String(length=50), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "date_of_birth >= '1900-01-01'", name=op.f("ck_patients_date_of_birth_min")
        ),
        sa.CheckConstraint(
            "emergency_contact_name IS NULL OR emergency_contact_name ~ "
            "'^[^\\W\\d_]+([ ''\\-][^\\W\\d_]+)*$'",
            name=op.f("ck_patients_emergency_contact_name_format"),
        ),
        sa.CheckConstraint(
            "emergency_contact_phone IS NULL OR emergency_contact_phone ~ "
            "'^[2-9]\\d{2}[2-9]\\d{6}$'",
            name=op.f("ck_patients_emergency_contact_phone_format"),
        ),
        sa.CheckConstraint(
            "first_name ~ '^[^\\W\\d_]+([ ''\\-][^\\W\\d_]+)*$'",
            name=op.f("ck_patients_first_name_format"),
        ),
        sa.CheckConstraint(
            "last_name ~ '^[^\\W\\d_]+([ ''\\-][^\\W\\d_]+)*$'",
            name=op.f("ck_patients_last_name_format"),
        ),
        sa.CheckConstraint(
            "phone_number ~ '^[2-9]\\d{2}[2-9]\\d{6}$'",
            name=op.f("ck_patients_phone_number_format"),
        ),
        sa.CheckConstraint(
            "sex IN ('Male', 'Female', 'Other', 'Decline to Answer')",
            name=op.f("ck_patients_sex_allowed_values"),
        ),
        sa.CheckConstraint(
            "state IN ('AK', 'AL', 'AR', 'AS', 'AZ', 'CA', 'CO', 'CT', 'DC', 'DE', 'FL', "
            "'GA', 'GU', 'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME', "
            "'MI', 'MN', 'MO', 'MP', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM', 'NV', "
            "'NY', 'OH', 'OK', 'OR', 'PA', 'PR', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VA', "
            "'VI', 'VT', 'WA', 'WI', 'WV', 'WY')",
            name=op.f("ck_patients_state_allowed_values"),
        ),
        sa.CheckConstraint(
            "zip_code ~ '^\\d{5}(-\\d{4})?$'", name=op.f("ck_patients_zip_code_format")
        ),
        sa.CheckConstraint(
            "length(trim(address_line_1)) >= 1", name=op.f("ck_patients_address_line_1_length")
        ),
        sa.CheckConstraint("length(trim(city)) >= 1", name=op.f("ck_patients_city_length")),
        sa.CheckConstraint(
            "length(trim(first_name)) >= 1", name=op.f("ck_patients_first_name_length")
        ),
        sa.CheckConstraint(
            "length(trim(last_name)) >= 1", name=op.f("ck_patients_last_name_length")
        ),
        sa.PrimaryKeyConstraint("patient_id", name=op.f("pk_patients")),
        sa.UniqueConstraint("source_call_id", name=op.f("uq_patients_source_call_id")),
    )
    op.create_index("ix_patients_date_of_birth", "patients", ["date_of_birth"], unique=False)
    op.create_index(
        "ix_patients_last_name_lower",
        "patients",
        [sa.literal_column("lower(last_name)")],
        unique=False,
    )
    op.create_index(
        "ix_patients_phone_number_active",
        "patients",
        ["phone_number"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # A CHECK constraint's expression must be immutable; CURRENT_DATE is only stable, so
    # "future date of birth" can't be enforced with a CHECK. A trigger can call it safely.
    op.execute(
        """
        CREATE FUNCTION reject_future_date_of_birth() RETURNS trigger AS $$
        BEGIN
            IF NEW.date_of_birth > CURRENT_DATE THEN
                RAISE EXCEPTION 'date_of_birth cannot be in the future';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER patients_reject_future_dob
        BEFORE INSERT OR UPDATE ON patients
        FOR EACH ROW
        EXECUTE FUNCTION reject_future_date_of_birth();
        """
    )

    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            -- clock_timestamp(), not now(): now() is frozen for the whole transaction,
            -- so back-to-back updates in one transaction would get an identical value.
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER patients_set_updated_at
        BEFORE UPDATE ON patients
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS patients_set_updated_at ON patients")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP TRIGGER IF EXISTS patients_reject_future_dob ON patients")
    op.execute("DROP FUNCTION IF EXISTS reject_future_date_of_birth()")

    op.drop_index(
        "ix_patients_phone_number_active",
        table_name="patients",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_patients_last_name_lower", table_name="patients")
    op.drop_index("ix_patients_date_of_birth", table_name="patients")
    op.drop_table("patients")
