"""Async SQLAlchemy engine and session factory, tuned for Neon's pooled endpoint.

Neon's pooled endpoint runs PgBouncer in transaction mode, which is incompatible with
asyncpg's server-side prepared statement cache, so it is disabled explicitly. SSL is
passed via `connect_args` (asyncpg does not understand a `sslmode` URL parameter).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def create_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        connect_args={
            "statement_cache_size": 0,
            "ssl": "require",
        },
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


async def dispose_engine() -> None:
    """Dispose the process-wide engine, e.g. during app shutdown."""
    await get_engine().dispose()
