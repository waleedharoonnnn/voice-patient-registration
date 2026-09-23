"""Validation for insurance member IDs."""

from __future__ import annotations

import re

_MEMBER_ID_RE = re.compile(r"^[A-Z0-9-]{1,50}$")


def validate_member_id(value: str) -> str:
    """Validate and normalize an insurance member ID: alphanumeric plus hyphens, 1-50 chars.

    The result is uppercased.
    """
    candidate = value.strip().upper()
    if not _MEMBER_ID_RE.match(candidate):
        raise ValueError(
            "Insurance member ID must be 1-50 characters, letters, numbers, and hyphens only."
        )
    return candidate
