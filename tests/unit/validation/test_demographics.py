"""Unit tests for app.validation.demographics."""

from __future__ import annotations

import pytest

from app.validation.demographics import normalize_language, normalize_sex


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Male", "Male"),
        ("male", "Male"),
        ("M", "Male"),
        ("man", "Male"),
        ("Female", "Female"),
        ("female", "Female"),
        ("F", "Female"),
        ("woman", "Female"),
        ("Other", "Other"),
        ("other", "Other"),
        ("Decline to Answer", "Decline to Answer"),
        ("decline", "Decline to Answer"),
        ("prefer not to say", "Decline to Answer"),
        ("rather not say", "Decline to Answer"),
        ("prefer not to answer", "Decline to Answer"),
    ],
)
def test_normalize_sex_valid(raw: str, expected: str) -> None:
    assert normalize_sex(raw) == expected


@pytest.mark.parametrize("raw", ["", "unknown", "x", "banana"])
def test_normalize_sex_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        normalize_sex(raw)


def test_normalize_language_defaults_to_english() -> None:
    assert normalize_language(None) == "English"
    assert normalize_language("") == "English"
    assert normalize_language("   ") == "English"


def test_normalize_language_title_cases() -> None:
    assert normalize_language("spanish") == "Spanish"
    assert normalize_language("MANDARIN CHINESE") == "Mandarin Chinese"
