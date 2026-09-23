"""Validation for person names (first, last, emergency contact name)."""

from __future__ import annotations

import re
import unicodedata

_NAME_RE = re.compile(r"^[^\W\d_]+([ '\-][^\W\d_]+)*$", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

MIN_LENGTH = 1
MAX_LENGTH = 50


def validate_name(value: str, *, field_name: str = "Name") -> str:
    """Trim, collapse inner whitespace, and validate a person's name.

    Allows letters (including accented letters), spaces, hyphens, and apostrophes.
    Raises ValueError with a speakable message on failure.
    """
    trimmed = _WHITESPACE_RE.sub(" ", value.strip())

    if not (MIN_LENGTH <= len(trimmed) <= MAX_LENGTH):
        raise ValueError(f"{field_name} must be between 1 and 50 characters.")

    normalized = unicodedata.normalize("NFC", trimmed)
    if not _NAME_RE.match(normalized):
        raise ValueError(
            f"{field_name} can only contain letters, spaces, hyphens, and apostrophes."
        )

    return normalized
