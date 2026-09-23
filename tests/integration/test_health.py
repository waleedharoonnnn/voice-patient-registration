"""Integration tests for the health endpoints and cross-cutting HTTP behavior."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.middleware import REQUEST_ID_HEADER


async def test_health_liveness_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ok"}
    assert body["error"] is None


async def test_health_ready_reports_503_when_db_unreachable(client: AsyncClient) -> None:
    # No real Postgres is running against the configured DATABASE_URL in this test env,
    # so the readiness probe must report the DB as unreachable rather than hang or 500.
    response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "not_ready"


async def test_unknown_route_returns_enveloped_404(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]


async def test_request_id_is_echoed_when_provided(client: AsyncClient) -> None:
    response = await client.get("/health", headers={REQUEST_ID_HEADER: "abc-123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc-123"


async def test_request_id_is_generated_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert REQUEST_ID_HEADER in response.headers
    assert response.headers[REQUEST_ID_HEADER]


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
