"""Caller-ID recognition: identify_caller / verify_caller over the real webhook + Postgres."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("clean_patients_table")

SECRET = {"X-Vapi-Secret": "test-webhook-secret"}
API_KEY = {"X-API-Key": "test-api-key"}
CALLER = "+12125550142"


def _patient(**overrides: str) -> dict[str, str]:
    return {
        "first_name": "Rosa",
        "last_name": "Callerton",
        "date_of_birth": "04/12/1979",
        "sex": "Female",
        "phone_number": "(212) 555-0142",
        "address_line_1": "5 Test Ave",
        "city": "Testville",
        "state": "NY",
        "zip_code": "10001",
        **overrides,
    }


def _tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    caller: str | None = CALLER,
    on_call_object: bool = False,
) -> dict[str, Any]:
    """Recorded-shape Vapi tool-calls message; caller ID in message.customer by default."""
    message: dict[str, Any] = {
        "type": "tool-calls",
        "call": {"id": "call-cid-1"},
        "toolCallList": [{"id": "tc-1", "function": {"name": name, "arguments": arguments or {}}}],
    }
    if caller is not None:
        if on_call_object:
            message["call"]["customer"] = {"number": caller}
        else:
            message["customer"] = {"number": caller}
    return {"message": message}


async def _result(client: AsyncClient, body: dict[str, Any]) -> str:
    response = await client.post("/vapi/webhook", json=body, headers=SECRET)
    assert response.status_code == 200
    result: str = response.json()["results"][0]["result"]
    return result


async def _create(client: AsyncClient, **overrides: str) -> str:
    response = await client.post("/patients", json=_patient(**overrides), headers=API_KEY)
    assert response.status_code == 201
    patient_id: str = response.json()["data"]["patient_id"]
    return patient_id


# --- identify_caller ----------------------------------------------------------------------


async def test_identify_without_caller_id_is_no_caller_id(client: AsyncClient) -> None:
    """Web calls (and withheld numbers) carry no customer.number."""
    assert await _result(client, _tool_call("identify_caller", caller=None)) == "NO_CALLER_ID"


async def test_identify_non_us_number_is_no_caller_id(client: AsyncClient) -> None:
    body = _tool_call("identify_caller", caller="+442079460000")
    assert await _result(client, body) == "NO_CALLER_ID"


async def test_identify_unknown_number_is_no_match(client: AsyncClient) -> None:
    assert await _result(client, _tool_call("identify_caller")) == "NO_MATCH"


async def test_identify_known_number_reveals_nothing(client: AsyncClient) -> None:
    await _create(client)
    result = await _result(client, _tool_call("identify_caller"))
    assert result == "CALLER_ON_FILE"
    assert "Rosa" not in result


async def test_identify_reads_caller_from_call_object_fallback(client: AsyncClient) -> None:
    await _create(client)
    body = _tool_call("identify_caller", on_call_object=True)
    assert await _result(client, body) == "CALLER_ON_FILE"


async def test_identify_ignores_soft_deleted_patients(client: AsyncClient) -> None:
    patient_id = await _create(client)
    await client.delete(f"/patients/{patient_id}", headers=API_KEY)
    assert await _result(client, _tool_call("identify_caller")) == "NO_MATCH"


# --- verify_caller -------------------------------------------------------------------------


async def test_verify_wrong_dob_is_mismatch_and_reveals_nothing(client: AsyncClient) -> None:
    await _create(client)
    result = await _result(client, _tool_call("verify_caller", {"date_of_birth": "01/01/1980"}))
    assert result == "IDENTITY_MISMATCH"


async def test_verify_invalid_dob_is_invalid(client: AsyncClient) -> None:
    await _create(client)
    result = await _result(client, _tool_call("verify_caller", {"date_of_birth": "13/45/1979"}))
    assert result.startswith("INVALID: date_of_birth")


async def test_verify_requires_caller_id(client: AsyncClient) -> None:
    body = _tool_call("verify_caller", {"date_of_birth": "04/12/1979"}, caller=None)
    assert await _result(client, body) == "NO_CALLER_ID"


async def test_verify_correct_dob_without_appointments(client: AsyncClient) -> None:
    patient_id = await _create(client)
    result = await _result(client, _tool_call("verify_caller", {"date_of_birth": "1979-04-12"}))
    assert result == (
        f"VERIFIED: patient_id={patient_id}; first_name=Rosa; upcoming_appointments=none"
    )


async def test_verify_lists_upcoming_appointment(client: AsyncClient) -> None:
    patient_id = await _create(client)
    slots = await _result(client, _tool_call("get_available_slots", {"time_of_day": "any"}))
    slot_id = slots.split("1) ")[1].split(" | ")[0]
    booked = await _result(
        client, _tool_call("book_appointment", {"patient_id": patient_id, "slot_id": slot_id})
    )
    assert booked.startswith("BOOKED:")

    result = await _result(client, _tool_call("verify_caller", {"date_of_birth": "04/12/1979"}))
    assert result.startswith(f"VERIFIED: patient_id={patient_id}; first_name=Rosa;")
    upcoming = result.split("upcoming_appointments=")[1]
    assert upcoming != "none"
    assert "Eastern with Dr." in upcoming
    # The same spoken time the booking confirmed.
    assert booked.split("time=")[1].removesuffix(" Eastern") in upcoming


async def test_verify_picks_the_right_person_on_a_shared_family_phone(
    client: AsyncClient,
) -> None:
    await _create(client)
    child_id = await _create(client, first_name="Leo", date_of_birth="09/30/2012", sex="Male")
    result = await _result(client, _tool_call("verify_caller", {"date_of_birth": "09/30/2012"}))
    assert result.startswith(f"VERIFIED: patient_id={child_id}; first_name=Leo;")


async def test_verified_caller_can_update_with_existing_tool(client: AsyncClient) -> None:
    """The flow after VERIFIED reuses update_patient (DOB re-checked server-side)."""
    patient_id = await _create(client)
    await _result(client, _tool_call("verify_caller", {"date_of_birth": "04/12/1979"}))
    updated = await _result(
        client,
        _tool_call(
            "update_patient",
            {"patient_id": patient_id, "date_of_birth": "04/12/1979", "fields": {"city": "Albany"}},
        ),
    )
    assert updated.startswith("UPDATED:")
