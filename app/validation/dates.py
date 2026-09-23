"""Validation and parsing for dates: date of birth and general calendar dates."""

from __future__ import annotations

from datetime import date, datetime

MIN_DATE_OF_BIRTH = date(1900, 1, 1)

_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")


def parse_calendar_date(value: str, *, field_name: str = "Date") -> date:
    """Parse 'MM/DD/YYYY' or 'YYYY-MM-DD', rejecting impossible dates (e.g. 02/30).

    No range checks (past/future) — see `parse_dob` for date-of-birth-specific rules.
    """
    for fmt in _FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{field_name} must be in MM/DD/YYYY or YYYY-MM-DD format.")


def parse_dob(value: str, *, today: date | None = None) -> date:
    """Parse a date of birth from 'MM/DD/YYYY' or 'YYYY-MM-DD'.

    Rejects impossible calendar dates (e.g. 02/30), dates before 1900-01-01, and dates
    in the future. `today` is injectable for deterministic testing.
    """
    current = today if today is not None else date.today()

    parsed = parse_calendar_date(value, field_name="Date of birth")

    if parsed > current:
        raise ValueError("Date of birth cannot be in the future.")

    if parsed < MIN_DATE_OF_BIRTH:
        raise ValueError("Date of birth cannot be before 1900-01-01.")

    return parsed
