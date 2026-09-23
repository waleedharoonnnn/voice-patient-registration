"""Unit tests for app.validation.names."""

from __future__ import annotations

import pytest

from app.validation.names import validate_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("O'Brien", "O'Brien"),
        ("Mary-Jane", "Mary-Jane"),
        ("José", "José"),
        ("Anne Marie", "Anne Marie"),
        ("  Jane  ", "Jane"),
        ("Jane   Doe", "Jane Doe"),
        ("A", "A"),
        ("a" * 50, "a" * 50),
    ],
)
def test_validate_name_valid(raw: str, expected: str) -> None:
    assert validate_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "a" * 51,
        "Jane123",
        "Jane_Doe",
        "Jane@Doe",
        "Jane.Doe",
        "123",
    ],
)
def test_validate_name_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        validate_name(raw)


def test_validate_name_uses_field_name_in_message() -> None:
    with pytest.raises(ValueError, match="First name"):
        validate_name("", field_name="First name")
