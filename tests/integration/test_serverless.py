"""Serverless (Vercel) deployment behavior: pool modes, proxy IP keying, static, shutdown."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from tests.integration.conftest import AppFactory

API_KEY = {"X-API-Key": "test-api-key"}
REPO_ROOT = Path(__file__).parent.parent.parent
VALID_PATIENT = {
    "first_name": "Nola",
    "last_name": "Serverless",
    "date_of_birth": "02/29/1988",
    "sex": "Other",
    "phone_number": "212-555-0177",
    "address_line_1": "9 Test Way",
    "city": "Testville",
    "state": "NY",
    "zip_code": "10001",
}


# --- DB_POOL_MODE ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "pool_class"), [("null", NullPool), ("queue", AsyncAdaptedQueuePool)]
)
async def test_pool_mode_selects_pool_class(
    mode: str, pool_class: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.session import create_engine

    monkeypatch.setenv("DB_POOL_MODE", mode)
    get_settings.cache_clear()
    engine = create_engine()
    try:
        assert isinstance(engine.pool, pool_class)
    finally:
        await engine.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize("mode", ["null", "queue"])
@pytest.mark.usefixtures("clean_patients_table")
async def test_app_round_trips_in_each_pool_mode(custom_client: AppFactory, mode: str) -> None:
    async with custom_client(DB_POOL_MODE=mode) as client:
        assert (await client.get("/health/ready")).status_code == 200
        created = await client.post("/patients", json=VALID_PATIENT, headers=API_KEY)
        assert created.status_code == 201
        patient_id = created.json()["data"]["patient_id"]
        fetched = await client.get(f"/patients/{patient_id}", headers=API_KEY)
        assert fetched.json()["data"]["last_name"] == "Serverless"


@pytest.mark.usefixtures("clean_patients_table")
async def test_null_pool_holds_no_connection_between_requests(custom_client: AppFactory) -> None:
    from sqlalchemy import event

    from app.db.session import get_engine

    opened: list[object] = []
    closed: list[object] = []
    async with custom_client(DB_POOL_MODE="null") as client:
        sync_engine = get_engine().sync_engine
        event.listen(sync_engine, "connect", lambda conn, _rec: opened.append(conn))
        event.listen(sync_engine, "close", lambda conn, _rec: closed.append(conn))
        for _ in range(2):
            assert (await client.get("/patients", headers=API_KEY)).status_code == 200
            # Each request's connection is really closed when released, not kept idle.
            assert len(opened) == len(closed)
    assert len(opened) == 2


def test_invalid_pool_mode_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("DB_POOL_MODE", "bogus")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings init kwarg


# --- Rate limiting behind Vercel's proxy ---------------------------------------------------


async def test_rate_limit_keys_on_trusted_proxy_ip_header(custom_client: AppFactory) -> None:
    async with custom_client(
        RATE_LIMIT_DEFAULT="2/minute", RATE_LIMIT_CLIENT_IP_HEADER="x-real-ip"
    ) as client:
        alice = {**API_KEY, "x-real-ip": "198.51.100.1"}
        bob = {**API_KEY, "x-real-ip": "198.51.100.2"}
        assert [(await client.get("/providers", headers=alice)).status_code for _ in range(3)] == [
            200,
            200,
            429,
        ]
        # A different client behind the same proxy has its own budget.
        assert (await client.get("/providers", headers=bob)).status_code == 200


async def test_forwarded_for_list_uses_first_hop(custom_client: AppFactory) -> None:
    async with custom_client(
        RATE_LIMIT_DEFAULT="1/minute", RATE_LIMIT_CLIENT_IP_HEADER="x-forwarded-for"
    ) as client:
        first = {**API_KEY, "x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        again = {**API_KEY, "x-forwarded-for": "203.0.113.9, 10.0.0.2"}
        assert (await client.get("/providers", headers=first)).status_code == 200
        assert (await client.get("/providers", headers=again)).status_code == 429


async def test_ip_header_ignored_unless_configured(custom_client: AppFactory) -> None:
    """Off Vercel, a client must not be able to dodge the limit by inventing headers."""
    async with custom_client(RATE_LIMIT_DEFAULT="1/minute") as client:
        one = {**API_KEY, "x-real-ip": "198.51.100.1"}
        two = {**API_KEY, "x-real-ip": "198.51.100.2"}
        assert (await client.get("/providers", headers=one)).status_code == 200
        assert (await client.get("/providers", headers=two)).status_code == 429


# --- Static files still get security headers -----------------------------------------------


async def test_static_files_get_security_headers(client: AsyncClient) -> None:
    response = await client.get("/static/dashboard.css")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in response.headers


def test_static_is_served_by_the_function_on_vercel() -> None:
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["vercel"]["fastapi"]["static"]["cdn"] is False


# --- Shutdown fits Vercel's 500 ms cleanup window ------------------------------------------


async def test_shutdown_is_bounded_even_if_dispose_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    async def _hang() -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(main_module, "dispose_engine", _hang)
    application = main_module.create_app()
    started = time.monotonic()
    async with application.router.lifespan_context(application):
        pass
    assert time.monotonic() - started < 0.5


# --- Vercel project config -----------------------------------------------------------------


def test_vercel_config_matches_entrypoint_and_limits() -> None:
    config = json.loads((REPO_ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["regions"] == ["iad1"]
    function = config["functions"]["app/main.py"]
    assert function["maxDuration"] == 30
    for excluded in ("tests/**", "docs/**", "scripts/**", "migrations/**"):
        assert excluded in function["excludeFiles"]
    # The runtime must never need anything we exclude.
    assert "app/" not in function["excludeFiles"]


def test_entrypoint_exposes_a_fastapi_app_named_app() -> None:
    from fastapi import FastAPI

    import app.main as main_module

    assert isinstance(main_module.app, FastAPI)
