"""Shared pytest fixtures: env setup, app factory, and an httpx AsyncClient."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_REQUIRED_ENV: dict[str, str] = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://voiceai:voiceai@localhost:5544/voiceai_test",
    "DATABASE_URL_DIRECT": "postgresql+asyncpg://voiceai:voiceai@localhost:5544/voiceai_test",
    "TEST_DATABASE_URL": "postgresql+asyncpg://voiceai:voiceai@localhost:5544/voiceai_test",
    "DB_SSL_REQUIRE": "false",
    # The suite makes hundreds of requests a minute from one client; the real limit is
    # exercised by tests/integration/test_security.py with its own small value.
    "RATE_LIMIT_DEFAULT": "100000/minute",
    "API_KEY": "test-api-key",
    "VAPI_WEBHOOK_SECRET": "test-webhook-secret",
    "DASHBOARD_USERNAME": "test-dashboard-user",
    "DASHBOARD_PASSWORD": "test-dashboard-password",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required settings are present for every test unless a test removes them."""
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


@pytest_asyncio.fixture
async def app(_env: None) -> AsyncGenerator[FastAPI]:
    # Import (and therefore Settings()) happens after env vars are set by the _env fixture.
    from app.core.config import get_settings
    from app.db.session import dispose_engine, get_engine, get_session_factory
    from app.main import create_app

    get_settings.cache_clear()
    application = create_app()
    yield application
    # The DB engine is cached process-wide (by design, for production), but each pytest
    # test gets its own event loop — a pooled connection opened under one test's loop is
    # unusable in the next. Dispose and clear so the next test builds a fresh one.
    await dispose_engine()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def clear_settings_cache() -> Any:
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def unset_env(_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all required env vars, for testing fail-fast config validation."""
    for key in _REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("VAPI_API_KEY", raising=False)
    for key in list(os.environ):
        if key.startswith(("API_KEY", "DATABASE_URL", "DASHBOARD_", "VAPI_")):
            monkeypatch.delenv(key, raising=False)
