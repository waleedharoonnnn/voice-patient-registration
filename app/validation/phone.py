"""Validation and normalization for US (NANP) phone numbers."""

from __future__ import annotations

import re

_DIGITS_RE = re.compile(r"\d")
_NANP_RE = re.compile(r"^[2-9]\d{2}[2-9]\d{6}$")


def normalize_us_phone(value: str, *, field_name: str = "Phone number") -> str:
    """Normalize a US phone number to exactly 10 digits, e.g. '2125550147'.

    Accepts common formats: '(212) 555-0147', '212.555.0147', '+1 212 555 0147',
    '12125550147', '2125550147'. Strips an optional leading country code '1'.
    Area code and exchange (first digit of each 3-digit group) must be 2-9 (NANP).
    """
    digits = "".join(_DIGITS_RE.findall(value))

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        raise ValueError(f"{field_name} must be a 10-digit US phone number.")

    if not _NANP_RE.match(digits):
        raise ValueError(
            f"{field_name} is not a valid US phone number "
            "(area code and exchange must start with 2-9)."
        )

    return digits
