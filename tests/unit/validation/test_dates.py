"""Unit tests for app.validation.dates."""

from __future__ import annotations

from datetime import date

import pytest

from app.validation.dates import parse_dob

TODAY = date(2026, 9, 24)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01/15/1990", date(1990, 1, 15)),
        ("1990-01-15", date(1990, 1, 15)),
        ("02/29/2000", date(2000, 2, 29)),  # leap day, valid
        ("09/24/2026", TODAY),  # today is valid
        ("01/01/1900", date(1900, 1, 1)),  # minimum boundary
    ],
)
def test_parse_dob_valid(raw: str, expected: date) -> None:
    assert parse_dob(raw, today=TODAY) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "02/29/2001",  # not a leap year
        "02/30/2000",  # impossible date
        "13/01/2000",  # invalid month
        "09/25/2026",  # tomorrow: future
        "12/31/1899",  # before 1900-01-01
        "01-15-1990",  # wrong separator
        "not a date",
        "",
    ],
)
def test_parse_dob_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        parse_dob(raw, today=TODAY)


def test_parse_dob_defaults_to_real_today_when_not_injected() -> None:
    result = parse_dob("01/01/2000")
    assert result == date(2000, 1, 1)
