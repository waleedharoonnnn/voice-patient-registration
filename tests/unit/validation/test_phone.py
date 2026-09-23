"""Unit tests for app.validation.phone."""

from __future__ import annotations

import pytest

from app.validation.phone import normalize_us_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(212) 555-0147", "2125550147"),
        ("212.555.0147", "2125550147"),
        ("+1 212 555 0147", "2125550147"),
        ("12125550147", "2125550147"),
        ("2125550147", "2125550147"),
        ("1-212-555-0147", "2125550147"),
        ("212 555 0147", "2125550147"),
    ],
)
def test_normalize_us_phone_valid(raw: str, expected: str) -> None:
    assert normalize_us_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1234567890",  # area code starts with 1
        "0125550147",  # area code starts with 0
        "2101550147",  # exchange starts with 1
        "2100550147",  # exchange starts with 0
        "12345",  # too short
        "212555014712345",  # too long
        "abcdefghij",  # no digits
        "",
    ],
)
def test_normalize_us_phone_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        normalize_us_phone(raw)
