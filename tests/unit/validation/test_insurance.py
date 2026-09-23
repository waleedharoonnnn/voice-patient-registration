"""Unit tests for app.validation.insurance."""

from __future__ import annotations

import pytest

from app.validation.insurance import validate_member_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc123", "ABC123"),
        ("ABC-123-XYZ", "ABC-123-XYZ"),
        ("  abc123  ", "ABC123"),
        ("a", "A"),
        ("a" * 50, "A" * 50),
    ],
)
def test_validate_member_id_valid(raw: str, expected: str) -> None:
    assert validate_member_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc 123", "abc_123", "abc@123", "a" * 51])
def test_validate_member_id_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        validate_member_id(raw)
