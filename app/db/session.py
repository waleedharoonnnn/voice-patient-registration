"""Async SQLAlchemy engine and session factory, tuned for Neon's pooled endpoint.

Neon's pooled endpoint runs PgBouncer in transaction mode, which is incompatible with
asyncpg's server-side prepared statement cache, so it is disabled explicitly. SSL is
passed via `connect_args` (asyncpg does not understand a `sslmode` URL parameter).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def create_engine() -> AsyncEngine:
    """Build the engine for the configured pool mode (see `Settings.DB_POOL_MODE`).

    `null` uses NullPool for serverless: each session opens a fresh connection to Neon's
    pooler and closes it on release, so a frozen or recycled function instance never holds
    a stale connection. `queue` keeps SQLAlchemy's default pool for long-lived processes.
    """
    settings = get_settings()
    connect_args: dict[str, object] = {"statement_cache_size": 0}
    if settings.DB_SSL_REQUIRE:
        connect_args["ssl"] = "require"
    if settings.DB_POOL_MODE == "null":
        # pool_pre_ping is pointless here: every connection is brand new.
        return create_async_engine(
            settings.DATABASE_URL, poolclass=NullPool, connect_args=connect_args
        )
    return create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        connect_args=connect_args,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    return create_engine()


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield one session per request; commit on success, roll back on error."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def webhook_session() -> AsyncIterator[AsyncSession]:
    """A session for one Vapi webhook request: commit on success, roll back on error.

    Unlike `get_db`, this is a context manager the webhook route opens *itself* (not a
    FastAPI dependency), so a database that's down at connect or commit time surfaces as
    an exception the route can turn into a spoken SAVE_FAILED result — never a 500 that
    leaves the caller in silence.

    Also caps statement duration so a slow query can't hang a live call. `is_local=true`
    scopes the timeout to this transaction; it never leaks to other sessions on the
    pooled connection.
    """
    settings = get_settings()
    async with get_session_factory()() as session:
        try:
            await session.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": str(settings.VAPI_WEBHOOK_DB_STATEMENT_TIMEOUT_MS)},
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the process-wide engine, e.g. during app shutdown."""
    await get_engine().dispose()
