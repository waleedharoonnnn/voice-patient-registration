"""Validation and parsing for date of birth."""

from __future__ import annotations

from datetime import date, datetime

MIN_DATE_OF_BIRTH = date(1900, 1, 1)

_FORMATS = ("%m/%d/%Y", "%Y-%m-%d")


def parse_dob(value: str, *, today: date | None = None) -> date:
    """Parse a date of birth from 'MM/DD/YYYY' or 'YYYY-MM-DD'.

    Rejects impossible calendar dates (e.g. 02/30), dates before 1900-01-01, and dates
    in the future. `today` is injectable for deterministic testing.
    """
    current = today if today is not None else date.today()

    parsed: date | None = None
    for fmt in _FORMATS:
        try:
            parsed = datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
        else:
            break

    if parsed is None:
        raise ValueError("Date of birth must be in MM/DD/YYYY or YYYY-MM-DD format.")

    if parsed > current:
        raise ValueError("Date of birth cannot be in the future.")

    if parsed < MIN_DATE_OF_BIRTH:
        raise ValueError("Date of birth cannot be before 1900-01-01.")

    return parsed
