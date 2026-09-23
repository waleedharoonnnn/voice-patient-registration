"""Validation for US state, ZIP code, and city."""

from __future__ import annotations

import re

# 50 states + DC + the 5 populated US territories the assessment scope includes:
# PR (Puerto Rico), GU (Guam), VI (US Virgin Islands), AS (American Samoa), MP (Northern
# Mariana Islands).
US_STATES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
    "PR": "Puerto Rico",
    "GU": "Guam",
    "VI": "US Virgin Islands",
    "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

# Reverse map for full-name -> code lookups, e.g. "california" -> "CA".
_NAME_TO_CODE: dict[str, str] = {name.lower(): code for code, name in US_STATES.items()}

_ZIP5_RE = re.compile(r"^\d{5}$")
_ZIP5_4_RE = re.compile(r"^\d{5}-\d{4}$")
_ZIP9_RE = re.compile(r"^\d{9}$")

CITY_MIN_LENGTH = 1
CITY_MAX_LENGTH = 100


def normalize_state(value: str) -> str:
    """Normalize a state to its 2-letter USPS code.

    Accepts a 2-letter code in any case ('ca', 'CA') or a full state name in any case
    ('california', 'California').
    """
    candidate = value.strip()
    upper = candidate.upper()
    if upper in US_STATES:
        return upper

    lower = candidate.lower()
    if lower in _NAME_TO_CODE:
        return _NAME_TO_CODE[lower]

    raise ValueError(
        "State must be a valid US state, DC, or territory (e.g. 'CA' or 'California')."
    )


def validate_zip(value: str) -> str:
    """Validate a ZIP code: 5 digits, or 5+4 with a hyphen, or 9 bare digits (-> ZIP+4)."""
    candidate = value.strip()

    if _ZIP5_RE.match(candidate) or _ZIP5_4_RE.match(candidate):
        return candidate

    if _ZIP9_RE.match(candidate):
        return f"{candidate[:5]}-{candidate[5:]}"

    raise ValueError("ZIP code must be 5 digits, or 5 plus 4 (e.g. '12345' or '12345-6789').")


def validate_city(value: str) -> str:
    """Validate a city name: 1-100 characters after trimming."""
    candidate = value.strip()
    if not (CITY_MIN_LENGTH <= len(candidate) <= CITY_MAX_LENGTH):
        raise ValueError("City must be between 1 and 100 characters.")
    return candidate
