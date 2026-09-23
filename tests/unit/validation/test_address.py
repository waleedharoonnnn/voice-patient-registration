"""Unit tests for app.validation.address."""

from __future__ import annotations

import pytest

from app.validation.address import normalize_state, validate_city, validate_zip


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CA", "CA"),
        ("ca", "CA"),
        ("California", "CA"),
        ("california", "CA"),
        ("New York", "NY"),
        ("new york", "NY"),
        ("DC", "DC"),
        ("District of Columbia", "DC"),
        ("PR", "PR"),
        ("Puerto Rico", "PR"),
    ],
)
def test_normalize_state_valid(raw: str, expected: str) -> None:
    assert normalize_state(raw) == expected


@pytest.mark.parametrize("raw", ["XX", "Atlantis", "", "Neverland", "ZZ"])
def test_normalize_state_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        normalize_state(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12345", "12345"),
        ("12345-6789", "12345-6789"),
        ("123456789", "12345-6789"),
    ],
)
def test_validate_zip_valid(raw: str, expected: str) -> None:
    assert validate_zip(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["1234", "123456", "abcde", "12345-678", "12345-67890", ""],
)
def test_validate_zip_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match="ZIP code must be 5 digits, or 5 plus 4"):
        validate_zip(raw)


def test_validate_city_valid() -> None:
    assert validate_city("  Springfield  ") == "Springfield"


@pytest.mark.parametrize("raw", ["", "   ", "a" * 101])
def test_validate_city_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        validate_city(raw)
