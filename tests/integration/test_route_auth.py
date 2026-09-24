"""Every route requires auth unless explicitly allow-listed as public.

Enumerates routes from the live OpenAPI schema (plus the dashboard, which is excluded
from the schema) and calls each without credentials. A new route that forgets its auth
dependency fails this test instead of silently exposing PII.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

# Public by design: liveness/readiness for load balancers, API docs (can be disabled in
# prod via ENABLE_API_DOCS=false), and the dashboard's own CSS.
PUBLIC_PATHS = {"/health", "/health/ready", "/openapi.json", "/docs", "/redoc"}

DASHBOARD_PATHS = [
    "/dashboard",
    "/dashboard/calls",
    "/dashboard/patients/00000000-0000-0000-0000-000000000001",
]


def _concrete(path: str) -> str:
    return path.replace("{patient_id}", "00000000-0000-0000-0000-000000000001")


async def test_every_non_public_route_rejects_anonymous_requests(
    app: FastAPI, client: AsyncClient
) -> None:
    schema = app.openapi()
    checked = 0
    for path, operations in schema["paths"].items():
        if path in PUBLIC_PATHS:
            continue
        for method in operations:
            response = await client.request(method.upper(), _concrete(path), json={})
            assert response.status_code == 401, f"{method.upper()} {path} -> {response.status_code}"
            checked += 1

    for path in DASHBOARD_PATHS:
        assert (await client.get(path)).status_code == 401, path
        checked += 1

    assert checked >= 12  # guard against the loop silently checking nothing


@pytest.mark.parametrize("path", ["/health", "/static/dashboard.css"])
async def test_public_routes_stay_public(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 200
