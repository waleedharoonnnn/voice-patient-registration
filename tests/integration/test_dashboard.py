"""Staff dashboard: auth, rendering, search, escaping, and security headers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("clean_patients_table")

AUTH = ("test-dashboard-user", "test-dashboard-password")
SECRET = {"X-Vapi-Secret": "test-webhook-secret"}
API_KEY = {"X-API-Key": "test-api-key"}
FIXTURES = Path(__file__).parent.parent / "fixtures" / "vapi"
XSS = "<script>alert(1)</script>"


async def _voice_patient(client: AsyncClient, call_id: str, transcript: str) -> str:
    payload = json.loads((FIXTURES / "create_patient.json").read_text())
    payload["message"]["call"]["id"] = call_id
    result = (await client.post("/vapi/webhook", json=payload, headers=SECRET)).json()
    patient_id: str = result["results"][0]["result"].split("patient_id=")[1].split(";")[0]
    eoc: dict[str, Any] = {
        "message": {
            "type": "end-of-call-report",
            "call": {"id": call_id},
            "artifact": {"transcript": transcript},
            "analysis": {"summary": f"Summary with {XSS}"},
        }
    }
    await client.post("/vapi/webhook", json=eoc, headers=SECRET)
    return patient_id


# --- Auth ---------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/calls", "/dashboard/patients/x"])
async def test_requires_credentials(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")
    assert "text/html" in response.headers["content-type"]


async def test_rejects_wrong_password(client: AsyncClient) -> None:
    response = await client.get("/dashboard", auth=("test-dashboard-user", "wrong"))
    assert response.status_code == 401


async def test_rejects_wrong_username(client: AsyncClient) -> None:
    response = await client.get("/dashboard", auth=("someone-else", "test-dashboard-password"))
    assert response.status_code == 401


# --- Headers ------------------------------------------------------------------------------


async def test_security_headers_on_dashboard(client: AsyncClient) -> None:
    response = await client.get("/dashboard", auth=AUTH)
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "style-src 'self'" in csp
    assert "script-src" not in csp  # falls back to default-src 'none': no scripts at all
    assert response.headers["cache-control"] == "no-store"
    assert "noindex" in response.headers["x-robots-tag"]


async def test_security_headers_even_on_401(client: AsyncClient) -> None:
    response = await client.get("/dashboard")
    assert response.headers["cache-control"] == "no-store"


async def test_no_inline_scripts_or_styles(client: AsyncClient) -> None:
    await _voice_patient(client, "call-dash-0", "hello")
    for path in ["/dashboard", "/dashboard/calls"]:
        html = (await client.get(path, auth=AUTH)).text
        assert "<script" not in html
        assert "style=" not in html


# --- Pages ---------------------------------------------------------------------------------


async def test_home_empty_state(client: AsyncClient) -> None:
    response = await client.get("/dashboard", auth=AUTH)
    assert response.status_code == 200
    assert "No patients yet." in response.text


async def test_home_lists_patients_with_formatted_phone(client: AsyncClient) -> None:
    await _voice_patient(client, "call-dash-1", "hello")
    response = await client.get("/dashboard", auth=AUTH)
    assert response.status_code == 200
    assert "Caller, Voice" in response.text
    assert "(212) 555-0188" in response.text
    assert "Registered today" in response.text


@pytest.mark.parametrize(
    ("query", "should_match"),
    [
        ("last_name=caller", True),
        ("last_name=CALLER", True),
        ("last_name=nobody", False),
        ("phone=212.555.0188", True),
        ("dob=01/01/1990", True),
        ("dob=1990-01-01", True),
        ("dob=02/02/1991", False),
    ],
)
async def test_search(client: AsyncClient, query: str, should_match: bool) -> None:
    await _voice_patient(client, "call-dash-2", "hello")
    html = (await client.get(f"/dashboard?{query}", auth=AUTH)).text
    assert ("Caller, Voice" in html) is should_match
    if not should_match:
        assert "No patients match that search." in html


async def test_invalid_search_input_shows_friendly_error(client: AsyncClient) -> None:
    response = await client.get("/dashboard?phone=123", auth=AUTH)
    assert response.status_code == 200
    assert "Phone number must be a 10-digit US phone number." in response.text


async def test_patient_detail_escapes_transcript_and_summary(client: AsyncClient) -> None:
    patient_id = await _voice_patient(client, "call-dash-3", f"User: {XSS}")
    response = await client.get(f"/dashboard/patients/{patient_id}", auth=AUTH)
    assert response.status_code == 200
    assert XSS not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "Show transcript" in response.text
    assert "Registered" in response.text  # outcome badge


async def test_calls_page_escapes_and_filters(client: AsyncClient) -> None:
    await _voice_patient(client, "call-dash-4", f"User: {XSS}")
    all_calls = await client.get("/dashboard/calls", auth=AUTH)
    assert XSS not in all_calls.text
    assert "Voice Caller" in all_calls.text

    abandoned_only = await client.get("/dashboard/calls?outcome=abandoned", auth=AUTH)
    assert "Voice Caller" not in abandoned_only.text
    assert "No calls with that outcome." in abandoned_only.text


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard/patients/00000000-0000-0000-0000-000000000999",
        "/dashboard/patients/not-a-uuid",
        "/dashboard/no-such-page",
    ],
)
async def test_styled_404(client: AsyncClient, path: str) -> None:
    response = await client.get(path, auth=AUTH)
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Not found" in response.text


async def test_static_css_served(client: AsyncClient) -> None:
    response = await client.get("/static/dashboard.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
