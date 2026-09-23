"""Validation for sex and preferred language."""

from __future__ import annotations

SEX_VALUES: tuple[str, ...] = ("Male", "Female", "Other", "Decline to Answer")

DEFAULT_LANGUAGE = "English"

# Common synonyms a caller might say, mapped to the canonical values in SEX_VALUES.
_SEX_SYNONYMS: dict[str, str] = {
    "male": "Male",
    "m": "Male",
    "man": "Male",
    "female": "Female",
    "f": "Female",
    "woman": "Female",
    "other": "Other",
    "decline to answer": "Decline to Answer",
    "decline": "Decline to Answer",
    "prefer not to say": "Decline to Answer",
    "rather not say": "Decline to Answer",
    "prefer not to answer": "Decline to Answer",
}


def normalize_sex(value: str) -> str:
    """Normalize a spoken/written sex value to one of SEX_VALUES.

    Recognizes common synonyms: 'M'/'man' -> 'Male', 'F'/'woman' -> 'Female',
    'prefer not to say'/'rather not say'/'decline' -> 'Decline to Answer'.
    """
    candidate = value.strip().lower()

    if candidate in _SEX_SYNONYMS:
        return _SEX_SYNONYMS[candidate]

    raise ValueError("Sex must be one of: Male, Female, Other, or Decline to Answer.")


def normalize_language(value: str | None) -> str:
    """Title-case a preferred language, defaulting to 'English' when blank."""
    if value is None or not value.strip():
        return DEFAULT_LANGUAGE
    return value.strip().title()
