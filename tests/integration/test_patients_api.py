"""Integration tests for the /patients REST API, against the local Docker Postgres."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("clean_patients_table")

API_KEY = {"X-API-Key": "test-api-key"}

VALID_PATIENT: dict[str, Any] = {
    "first_name": "Jane",
    "last_name": "Doe",
    "date_of_birth": "06/15/1985",
    "sex": "Female",
    "phone_number": "(212) 555-0100",
    "email": "jane@example.com",
    "address_line_1": "123 Fake St",
    "city": "Springfield",
    "state": "IL",
    "zip_code": "62704",
}


def _assert_envelope_ok(body: dict[str, Any]) -> None:
    assert "data" in body
    assert body["error"] is None


def _assert_envelope_error(body: dict[str, Any], code: str) -> None:
    assert body["data"] is None
    assert body["error"]["code"] == code


async def _create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload = {**VALID_PATIENT, **overrides}
    response = await client.post("/patients", json=payload, headers=API_KEY)
    assert response.status_code == 201, response.text
    body = response.json()
    _assert_envelope_ok(body)
    return body["data"]


# --- POST /patients ------------------------------------------------------------------


async def test_create_patient_happy_path(client: AsyncClient) -> None:
    data = await _create(client)
    assert data["first_name"] == "Jane"
    assert data["phone_number"] == "2125550100"  # normalized
    assert data["date_of_birth"] == "1985-06-15"  # ISO in response
    assert data["preferred_language"] == "English"
    assert data["patient_id"]
    assert data["created_at"]
    assert "source_call_id" not in data


async def test_create_patient_validation_failure(client: AsyncClient) -> None:
    response = await client.post(
        "/patients", json={**VALID_PATIENT, "date_of_birth": "01/01/2099"}, headers=API_KEY
    )
    assert response.status_code == 422
    _assert_envelope_error(response.json(), "validation_failed")


async def test_create_patient_malformed_json_is_400(client: AsyncClient) -> None:
    response = await client.post(
        "/patients",
        content=b'{"first_name": ',
        headers={**API_KEY, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "data": None,
        "error": {
            "code": "malformed_request",
            "message": "Request body is not valid JSON.",
            "details": None,
        },
    }


async def test_create_patient_rejects_extra_fields(client: AsyncClient) -> None:
    response = await client.post(
        "/patients", json={**VALID_PATIENT, "unexpected_field": "x"}, headers=API_KEY
    )
    assert response.status_code == 422
    _assert_envelope_error(response.json(), "validation_failed")


async def test_create_patient_requires_api_key(client: AsyncClient) -> None:
    response = await client.post("/patients", json=VALID_PATIENT)
    assert response.status_code == 401
    _assert_envelope_error(response.json(), "unauthorized")


async def test_create_patient_wrong_api_key(client: AsyncClient) -> None:
    response = await client.post("/patients", json=VALID_PATIENT, headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


# --- GET /patients/{id} ---------------------------------------------------------------


async def test_get_patient_by_id(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.get(f"/patients/{created['patient_id']}", headers=API_KEY)
    assert response.status_code == 200
    body = response.json()
    _assert_envelope_ok(body)
    assert body["data"]["patient_id"] == created["patient_id"]


async def test_get_patient_not_found(client: AsyncClient) -> None:
    response = await client.get(f"/patients/{uuid.uuid4()}", headers=API_KEY)
    assert response.status_code == 404
    _assert_envelope_error(response.json(), "not_found")


async def test_get_patient_malformed_uuid_is_404_not_500(client: AsyncClient) -> None:
    response = await client.get("/patients/not-a-uuid", headers=API_KEY)
    assert response.status_code == 404
    _assert_envelope_error(response.json(), "not_found")


async def test_get_patient_requires_api_key(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.get(f"/patients/{created['patient_id']}")
    assert response.status_code == 401


# --- PUT /patients/{id} ----------------------------------------------------------------


async def test_update_patient_partial(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.put(
        f"/patients/{created['patient_id']}", json={"city": "New City"}, headers=API_KEY
    )
    assert response.status_code == 200
    body = response.json()
    _assert_envelope_ok(body)
    assert body["data"]["city"] == "New City"
    assert body["data"]["first_name"] == "Jane"  # unspecified fields unchanged


async def test_update_patient_changes_updated_at(client: AsyncClient) -> None:
    created = await _create(client)
    before = created["updated_at"]
    response = await client.put(
        f"/patients/{created['patient_id']}", json={"city": "Another City"}, headers=API_KEY
    )
    assert response.status_code == 200
    after = response.json()["data"]["updated_at"]
    assert after != before


async def test_update_patient_not_found(client: AsyncClient) -> None:
    response = await client.put(f"/patients/{uuid.uuid4()}", json={"city": "X"}, headers=API_KEY)
    assert response.status_code == 404
    _assert_envelope_error(response.json(), "not_found")


async def test_update_patient_rejects_explicit_null_required_field(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.put(
        f"/patients/{created['patient_id']}", json={"first_name": None}, headers=API_KEY
    )
    assert response.status_code == 422
    _assert_envelope_error(response.json(), "validation_failed")


async def test_update_patient_rejects_extra_fields(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.put(
        f"/patients/{created['patient_id']}", json={"nope": "x"}, headers=API_KEY
    )
    assert response.status_code == 422


async def test_update_patient_requires_api_key(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.put(f"/patients/{created['patient_id']}", json={"city": "X"})
    assert response.status_code == 401


# --- DELETE /patients/{id} --------------------------------------------------------------


async def test_delete_patient_soft_deletes_and_returns_record(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.delete(f"/patients/{created['patient_id']}", headers=API_KEY)
    assert response.status_code == 200
    body = response.json()
    _assert_envelope_ok(body)
    assert body["data"]["deleted_at"] is not None


async def test_deleted_patient_hidden_from_get(client: AsyncClient) -> None:
    created = await _create(client)
    await client.delete(f"/patients/{created['patient_id']}", headers=API_KEY)
    response = await client.get(f"/patients/{created['patient_id']}", headers=API_KEY)
    assert response.status_code == 404


async def test_deleted_patient_hidden_from_list(client: AsyncClient) -> None:
    created = await _create(client)
    await client.delete(f"/patients/{created['patient_id']}", headers=API_KEY)
    response = await client.get("/patients", headers=API_KEY)
    ids = [p["patient_id"] for p in response.json()["data"]["items"]]
    assert created["patient_id"] not in ids


async def test_delete_patient_not_found(client: AsyncClient) -> None:
    response = await client.delete(f"/patients/{uuid.uuid4()}", headers=API_KEY)
    assert response.status_code == 404


async def test_delete_patient_requires_api_key(client: AsyncClient) -> None:
    created = await _create(client)
    response = await client.delete(f"/patients/{created['patient_id']}")
    assert response.status_code == 401


# --- GET /patients (list + filters + pagination) ----------------------------------------


async def test_list_patients_requires_api_key(client: AsyncClient) -> None:
    response = await client.get("/patients")
    assert response.status_code == 401


async def test_list_patients_filter_last_name_case_insensitive(client: AsyncClient) -> None:
    await _create(client, last_name="Davis", phone_number="2125550101")
    await _create(client, last_name="Smith", phone_number="2125550102")

    response = await client.get("/patients?last_name=davis", headers=API_KEY)
    body = response.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["last_name"] == "Davis"


async def test_list_patients_filter_date_of_birth_both_formats(client: AsyncClient) -> None:
    await _create(client, date_of_birth="03/04/1995", phone_number="2125550103")

    for query_dob in ("1995-03-04", "03/04/1995"):
        response = await client.get(f"/patients?date_of_birth={query_dob}", headers=API_KEY)
        body = response.json()["data"]
        assert body["total"] == 1, query_dob


async def test_list_patients_filter_phone_messy_format(client: AsyncClient) -> None:
    await _create(client, phone_number="2125550104")

    response = await client.get("/patients?phone_number=%28212%29+555-0104", headers=API_KEY)
    body = response.json()["data"]
    assert body["total"] == 1


async def test_list_patients_pagination_bounds(client: AsyncClient) -> None:
    response = await client.get("/patients?limit=0", headers=API_KEY)
    assert response.status_code == 422

    response = await client.get("/patients?limit=101", headers=API_KEY)
    assert response.status_code == 422

    response = await client.get("/patients?offset=-1", headers=API_KEY)
    assert response.status_code == 422


async def test_list_patients_pagination_default_and_custom(client: AsyncClient) -> None:
    for i in range(3):
        await _create(client, phone_number=f"212555020{i}")

    response = await client.get("/patients?limit=2&offset=0", headers=API_KEY)
    body = response.json()["data"]
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
