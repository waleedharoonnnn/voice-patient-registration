"""Integration tests for the `patients` table: migrations, DB-level constraints, triggers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from alembic import command
from alembic.config import Config
from scripts.seed import seed
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

_VALID_PATIENT: dict[str, object] = {
    "first_name": "Test",
    "last_name": "Patient",
    "date_of_birth": date(1990, 1, 1),
    "sex": "Female",
    "phone_number": "2125550199",
    "address_line_1": "1 Test St",
    "city": "Testville",
    "state": "IL",
    "zip_code": "62704",
}

_INSERT_COLUMNS = ", ".join(_VALID_PATIENT)
_INSERT_PARAMS = ", ".join(f":{col}" for col in _VALID_PATIENT)
_INSERT_SQL = f"INSERT INTO patients ({_INSERT_COLUMNS}) VALUES ({_INSERT_PARAMS})"  # noqa: S608 (fixed column names, values are bound params)


async def _insert(conn: AsyncConnection, **overrides: object) -> None:
    params = {**_VALID_PATIENT, **overrides}
    await conn.execute(text(_INSERT_SQL), params)


def test_migration_round_trip(test_database_url: str) -> None:
    """upgrade -> downgrade -> upgrade must succeed without manual intervention.

    Deliberately a sync test: alembic's `command` API runs its own event loop
    internally (via asyncio.run), which cannot be nested inside pytest-asyncio's loop.
    """
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_database_url)

    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    # Leave the schema at head for every other test in the session.


async def test_valid_insert_succeeds(db_conn: AsyncConnection) -> None:
    await _insert(db_conn)
    result = await db_conn.execute(text("SELECT count(*) FROM patients"))
    assert result.scalar() == 1


async def test_rejects_invalid_state(db_conn: AsyncConnection) -> None:
    with pytest.raises(DBAPIError):
        async with db_conn.begin_nested():
            await _insert(db_conn, state="ZZ")


async def test_rejects_invalid_zip(db_conn: AsyncConnection) -> None:
    with pytest.raises(DBAPIError):
        async with db_conn.begin_nested():
            await _insert(db_conn, zip_code="1234")


async def test_rejects_invalid_phone(db_conn: AsyncConnection) -> None:
    with pytest.raises(DBAPIError):
        async with db_conn.begin_nested():
            await _insert(db_conn, phone_number="1125550199")  # area code starts with 1


async def test_rejects_future_date_of_birth(db_conn: AsyncConnection) -> None:
    tomorrow = date.today() + timedelta(days=1)
    with pytest.raises(DBAPIError):
        async with db_conn.begin_nested():
            await _insert(db_conn, date_of_birth=tomorrow)


async def test_rejects_invalid_sex(db_conn: AsyncConnection) -> None:
    with pytest.raises(DBAPIError):
        async with db_conn.begin_nested():
            await _insert(db_conn, sex="Unknown")


async def test_rejects_invalid_name_format(db_conn: AsyncConnection) -> None:
    with pytest.raises(DBAPIError):
        async with db_conn.begin_nested():
            await _insert(db_conn, first_name="Test123")


async def test_updated_at_changes_on_update_but_not_created_at(
    db_conn: AsyncConnection,
) -> None:
    await _insert(db_conn)
    before = (await db_conn.execute(text("SELECT created_at, updated_at FROM patients"))).one()

    await db_conn.execute(text("UPDATE patients SET city = 'NewCity'"))
    after = (await db_conn.execute(text("SELECT created_at, updated_at FROM patients"))).one()

    assert after.created_at == before.created_at
    assert after.updated_at > before.updated_at


async def test_patient_id_and_timestamps_autogenerate(db_conn: AsyncConnection) -> None:
    await _insert(db_conn)
    row = (
        await db_conn.execute(
            text(
                "SELECT patient_id, created_at, updated_at, preferred_language, deleted_at "
                "FROM patients"
            )
        )
    ).one()

    assert row.patient_id is not None
    assert row.created_at is not None
    assert row.updated_at is not None
    assert row.preferred_language == "English"
    assert row.deleted_at is None


async def test_seed_script_is_idempotent(
    db_conn: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.seed as seed_module

    def _fake_get_session_factory() -> object:
        return lambda: AsyncSession(
            bind=db_conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

    monkeypatch.setattr(seed_module, "get_session_factory", _fake_get_session_factory)

    await seed()
    await seed()

    result = await db_conn.execute(text("SELECT count(*) FROM patients"))
    assert result.scalar() == 2
