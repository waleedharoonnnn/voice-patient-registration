"""Seed the database with a small number of obviously-fake patients for local dev/demo use.

Idempotent: each patient has a fixed `patient_id`, and the insert upserts on that key, so
running this script multiple times always leaves exactly the same rows. Refuses to run
against APP_ENV=prod unless --force is passed, since seed data has no place in production.

Usage: `uv run python -m scripts.seed` (or `make seed`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date

from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.db.session import dispose_engine, get_session_factory
from app.models.patient import Patient

# Fixed IDs make re-runs idempotent (upsert on primary key) instead of inserting duplicates.
_SEED_PATIENTS: list[dict[str, object]] = [
    {
        "patient_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": date(1985, 6, 15),
        "sex": "Female",
        "phone_number": "2125550100",
        "email": "jane.doe.seed@example.com",
        "address_line_1": "123 Fake Street",
        "address_line_2": None,
        "city": "Springfield",
        "state": "IL",
        "zip_code": "62704",
        "preferred_language": "English",
        "emergency_contact_name": "John Doe",
        "emergency_contact_phone": "2125550101",
        "insurance_provider": "Fakecare Insurance",
        "insurance_member_id": "FAKE12345",
    },
    {
        "patient_id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
        "first_name": "Carlos",
        "last_name": "O'Rourke-Martinez",
        "date_of_birth": date(1972, 11, 2),
        "sex": "Male",
        "phone_number": "3125550102",
        "email": "carlos.seed@example.com",
        "address_line_1": "456 Fictional Ave",
        "address_line_2": "Apt 3B",
        "city": "Chicago",
        "state": "IL",
        "zip_code": "60601-1234",
        "preferred_language": "Spanish",
        "emergency_contact_name": "Maria Martinez",
        "emergency_contact_phone": "3125550103",
        "insurance_provider": None,
        "insurance_member_id": None,
    },
]


async def seed() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        for patient in _SEED_PATIENTS:
            update_columns = {key: value for key, value in patient.items() if key != "patient_id"}
            stmt = insert(Patient).values(**patient)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Patient.patient_id], set_=update_columns
            )
            await session.execute(stmt)
        await session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow seeding even when APP_ENV=prod.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.APP_ENV == "prod" and not args.force:
        print(
            "Refusing to seed: APP_ENV=prod. Pass --force to override.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    async def run() -> None:
        try:
            await seed()
        finally:
            await dispose_engine()

    asyncio.run(run())
    print(f"Seeded {len(_SEED_PATIENTS)} patient(s).")


if __name__ == "__main__":
    main()
