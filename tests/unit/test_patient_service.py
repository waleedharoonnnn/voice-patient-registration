"""Unit tests for PatientService — the non-trivial business rules, no DB involved."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.errors import NotFoundError
from app.models.patient import Patient
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services.patient_service import PatientService


def _make_patient(**overrides: object) -> Patient:
    defaults: dict[str, object] = {
        "patient_id": uuid.uuid4(),
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": date(1990, 1, 1),
        "sex": "Female",
        "phone_number": "2125550100",
        "email": None,
        "address_line_1": "1 St",
        "address_line_2": None,
        "city": "City",
        "state": "IL",
        "zip_code": "62704",
        "insurance_provider": None,
        "insurance_member_id": None,
        "preferred_language": "English",
        "emergency_contact_name": None,
        "emergency_contact_phone": None,
        "source_call_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "deleted_at": None,
    }
    defaults.update(overrides)
    return Patient(**defaults)


def _valid_create() -> PatientCreate:
    return PatientCreate(
        first_name="Jane",
        last_name="Doe",
        date_of_birth=date(1990, 1, 1),
        sex="Female",
        phone_number="2125550100",
        address_line_1="1 St",
        city="City",
        state="IL",
        zip_code="62704",
    )


@pytest.fixture
def repo() -> AsyncMock:
    return AsyncMock(spec=PatientRepository)


@pytest.fixture
def service(repo: AsyncMock) -> PatientService:
    return PatientService(repo)


async def test_create_patient_inserts_when_no_source_call_id(
    service: PatientService, repo: AsyncMock
) -> None:
    created = _make_patient()
    repo.create.return_value = created

    patient, was_created = await service.create_patient(_valid_create())

    assert was_created is True
    assert patient is created
    repo.get_by_source_call_id.assert_not_called()
    repo.create.assert_awaited_once()


async def test_create_patient_is_idempotent_on_source_call_id(
    service: PatientService, repo: AsyncMock
) -> None:
    existing = _make_patient(source_call_id="call-123")
    repo.get_by_source_call_id.return_value = existing

    patient, was_created = await service.create_patient(_valid_create(), source_call_id="call-123")

    assert was_created is False
    assert patient is existing
    repo.create.assert_not_called()


async def test_create_patient_inserts_when_source_call_id_not_seen_before(
    service: PatientService, repo: AsyncMock
) -> None:
    repo.get_by_source_call_id.return_value = None
    created = _make_patient(source_call_id="call-456")
    repo.create.return_value = created

    patient, was_created = await service.create_patient(_valid_create(), source_call_id="call-456")

    assert was_created is True
    assert patient is created
    repo.create.assert_awaited_once()
    call_kwargs = repo.create.await_args.args[0]
    assert call_kwargs["source_call_id"] == "call-456"


async def test_update_patient_not_found_raises(service: PatientService, repo: AsyncMock) -> None:
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundError):
        await service.update_patient(uuid.uuid4(), PatientUpdate(city="X"))


async def test_update_patient_applies_only_provided_fields(
    service: PatientService, repo: AsyncMock
) -> None:
    existing = _make_patient()
    repo.get_by_id.return_value = existing
    repo.update.return_value = _make_patient(city="New City")

    await service.update_patient(existing.patient_id, PatientUpdate(city="New City"))

    repo.update.assert_awaited_once_with(existing, {"city": "New City"})


async def test_delete_patient_not_found_raises(service: PatientService, repo: AsyncMock) -> None:
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundError):
        await service.delete_patient(uuid.uuid4())


async def test_delete_patient_soft_deletes_existing(
    service: PatientService, repo: AsyncMock
) -> None:
    existing = _make_patient()
    repo.get_by_id.return_value = existing
    deleted = _make_patient(deleted_at=datetime.now(UTC))
    repo.soft_delete.return_value = deleted

    result = await service.delete_patient(existing.patient_id)

    assert result is deleted
    repo.soft_delete.assert_awaited_once_with(existing)


async def test_verify_identity_true_when_dob_matches(
    service: PatientService, repo: AsyncMock
) -> None:
    existing = _make_patient(date_of_birth=date(1990, 1, 1))
    repo.get_by_id.return_value = existing

    assert await service.verify_identity(existing.patient_id, date(1990, 1, 1)) is True


async def test_verify_identity_false_when_dob_mismatches(
    service: PatientService, repo: AsyncMock
) -> None:
    existing = _make_patient(date_of_birth=date(1990, 1, 1))
    repo.get_by_id.return_value = existing

    assert await service.verify_identity(existing.patient_id, date(1991, 1, 1)) is False


async def test_verify_identity_false_when_patient_missing(
    service: PatientService, repo: AsyncMock
) -> None:
    repo.get_by_id.return_value = None

    assert await service.verify_identity(uuid.uuid4(), date(1990, 1, 1)) is False


async def test_find_by_phone_delegates_to_active_lookup(
    service: PatientService, repo: AsyncMock
) -> None:
    matches = [_make_patient()]
    repo.find_active_by_phone.return_value = matches

    result = await service.find_by_phone("2125550100")

    assert result is matches
    repo.find_active_by_phone.assert_awaited_once_with("2125550100")
