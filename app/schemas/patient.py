"""Pydantic request/response models for `/patients`.

Every field validator delegates to `app/validation/` (the single source of truth also
used by the voice tool handlers), so a rule is never implemented twice.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.validation.address import normalize_state, validate_city, validate_zip
from app.validation.dates import parse_dob
from app.validation.demographics import normalize_language, normalize_sex
from app.validation.email import validate_email
from app.validation.insurance import validate_member_id
from app.validation.names import validate_name
from app.validation.phone import normalize_us_phone

REQUIRED_FIELDS: tuple[str, ...] = (
    "first_name",
    "last_name",
    "date_of_birth",
    "sex",
    "phone_number",
    "address_line_1",
    "city",
    "state",
    "zip_code",
)


class _PatientFieldValidators:
    """Field validators shared by `PatientCreate` and `PatientUpdate`.

    A plain mixin (not a `BaseModel`) so pydantic collects these validators onto
    whichever concrete model declares a field of the same name, without duplicating the
    validation logic between the create and update schemas.
    """

    # first_name..zip_code are required on PatientCreate (so pydantic never lets `v` be
    # None there) but optional on PatientUpdate, where an explicit `null` must fall
    # through to `_reject_null_required_fields` below rather than crash here.

    @field_validator("first_name")
    @classmethod
    def _validate_first_name(cls, v: str | None) -> str | None:
        return validate_name(v, field_name="First name") if v is not None else v

    @field_validator("last_name")
    @classmethod
    def _validate_last_name(cls, v: str | None) -> str | None:
        return validate_name(v, field_name="Last name") if v is not None else v

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _validate_date_of_birth(cls, v: object) -> object:
        if isinstance(v, str):
            return parse_dob(v)
        return v

    @field_validator("sex")
    @classmethod
    def _validate_sex(cls, v: str | None) -> str | None:
        return normalize_sex(v) if v is not None else v

    @field_validator("phone_number")
    @classmethod
    def _validate_phone_number(cls, v: str | None) -> str | None:
        return normalize_us_phone(v, field_name="Phone number") if v is not None else v

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        return validate_email(v) if v is not None else v

    @field_validator("address_line_1")
    @classmethod
    def _validate_address_line_1(cls, v: str | None) -> str | None:
        if v is None:
            return v
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Address line 1 is required.")
        return trimmed

    @field_validator("address_line_2")
    @classmethod
    def _validate_address_line_2(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else v

    @field_validator("city")
    @classmethod
    def _validate_city(cls, v: str | None) -> str | None:
        return validate_city(v) if v is not None else v

    @field_validator("state")
    @classmethod
    def _validate_state(cls, v: str | None) -> str | None:
        return normalize_state(v) if v is not None else v

    @field_validator("zip_code")
    @classmethod
    def _validate_zip_code(cls, v: str | None) -> str | None:
        return validate_zip(v) if v is not None else v

    @field_validator("insurance_provider")
    @classmethod
    def _validate_insurance_provider(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else v

    @field_validator("insurance_member_id")
    @classmethod
    def _validate_insurance_member_id(cls, v: str | None) -> str | None:
        return validate_member_id(v) if v is not None else v

    @field_validator("preferred_language")
    @classmethod
    def _validate_preferred_language(cls, v: str) -> str:
        return normalize_language(v)

    @field_validator("emergency_contact_name")
    @classmethod
    def _validate_emergency_contact_name(cls, v: str | None) -> str | None:
        return validate_name(v, field_name="Emergency contact name") if v is not None else v

    @field_validator("emergency_contact_phone")
    @classmethod
    def _validate_emergency_contact_phone(cls, v: str | None) -> str | None:
        return normalize_us_phone(v, field_name="Emergency contact phone") if v is not None else v


class PatientCreate(_PatientFieldValidators, BaseModel):
    """Request body for `POST /patients`. Every spec field, required exactly per spec."""

    model_config = ConfigDict(extra="forbid")

    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str = "English"
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class PatientUpdate(_PatientFieldValidators, BaseModel):
    """Request body for `PUT /patients/{id}`.

    Every field is optional so the caller can send a partial update. A field omitted
    entirely is left unchanged (see `REQUIRED_FIELDS` handling below); an optional field
    explicitly set to `null` clears it. A *required* field explicitly set to `null` is
    rejected with 422, since that would leave the record in an invalid state.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    phone_number: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    @model_validator(mode="after")
    def _reject_null_required_fields(self) -> Self:
        nulled = [
            field
            for field in REQUIRED_FIELDS
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if nulled:
            raise ValueError(
                "These fields are required and cannot be set to null: " + ", ".join(nulled)
            )
        return self

    def provided_fields(self) -> dict[str, object]:
        """Fields the caller actually sent, for a partial update (omitted vs. null)."""
        return self.model_dump(exclude_unset=True)


class PatientOut(BaseModel):
    """Response body for a patient. Every column except `source_call_id`."""

    model_config = ConfigDict(from_attributes=True)

    patient_id: UUID
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class PatientListQuery(BaseModel):
    """Query params for `GET /patients`."""

    model_config = ConfigDict(extra="forbid")

    last_name: str | None = Field(default=None, description="Case-insensitive exact match.")
    # Deliberately `str`, not `date`: FastAPI resolves a Depends()-model's fields using
    # their own annotation *before* this model's validators run, so a `date`-typed field
    # would only ever accept ISO format (rejecting MM/DD/YYYY at the FastAPI layer,
    # before app.validation.dates.parse_dob ever saw it). The router parses this string.
    date_of_birth: str | None = Field(default=None, description="MM/DD/YYYY or YYYY-MM-DD.")
    phone_number: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("phone_number")
    @classmethod
    def _normalize_phone_number(cls, v: str | None) -> str | None:
        return normalize_us_phone(v, field_name="Phone number") if v is not None else v

    @field_validator("last_name")
    @classmethod
    def _trim_last_name(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v


class PatientListOut(BaseModel):
    """Response body for `GET /patients`: a page of results plus pagination info."""

    items: list[PatientOut]
    total: int
    limit: int
    offset: int
