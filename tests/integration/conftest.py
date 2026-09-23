"""Fixtures for DB integration tests: apply migrations once per session, then give each
test its own engine, connection, and transaction (rolled back afterward) so tests never
leak state to each other or share an asyncpg connection across event loops.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import get_settings


def _alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def test_database_url() -> str:
    # Session-scoped: reads the real process environment / .env directly rather than
    # depending on the function-scoped `_env` fixture (which pytest's scope rules forbid
    # a session fixture from using).
    settings = get_settings()
    assert settings.TEST_DATABASE_URL, "TEST_DATABASE_URL must be set for integration tests."
    return settings.TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema(test_database_url: str) -> None:
    """Bring the local Docker Postgres schema to head once per test session."""
    command.upgrade(_alembic_config(test_database_url), "head")


@pytest_asyncio.fixture
async def db_conn(
    test_database_url: str, _migrated_schema: None
) -> AsyncGenerator[AsyncConnection]:
    """A connection wrapped in a transaction that is always rolled back after the test.

    A fresh engine per test (rather than a session-scoped one) keeps every asyncpg
    connection bound to the event loop pytest-asyncio creates for that test.

    Tests that need to assert a statement is rejected should wrap it in
    `async with db_conn.begin_nested(): ...` so the expected failure doesn't invalidate
    the outer per-test transaction.
    """
    engine = create_async_engine(test_database_url)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                yield conn
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def clean_patients_table(
    test_database_url: str, _migrated_schema: None
) -> AsyncGenerator[None]:
    """For tests that go through the real HTTP app (which commits per request, so the
    rollback-based `db_conn` isolation doesn't apply): start each test with an empty table.
    """
    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE patients"))
    await engine.dispose()
    yield
