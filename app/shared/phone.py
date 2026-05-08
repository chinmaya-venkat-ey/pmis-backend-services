"""Shared phone-number validation helper (mirror of monolith).

Used by the vendor schema (``app/api/v3/vendors/schemas.py``) to apply a
consistent "is this even a phone number?" check on the wire.

Rules (deliberately loose to accept the international formats the FE
typically sees):

  * Strip whitespace, hyphens, parens, and dots — these are display
    separators that vary by locale.
  * Allow a single optional leading ``+`` (E.164 country-code marker).
  * The remaining characters must be **all digits**.
  * Total digit count must be in ``[7, 15]`` — covers Indian 10-digit
    mobiles, Indian with ``+91`` country code (12), and the broader
    E.164 limit of 15 digits including country code.
  * Empty / whitespace-only input is rejected.

Returns the input unchanged on success (just the trailing/leading
whitespace stripped) so the FE keeps full control over display
formatting. Storage retains whatever the caller sent — only the
gate runs.

Raises ``ValueError`` with a stable message that surfaces in the 422
body so the FE can show it inline next to the field.
"""
from __future__ import annotations

import re


# Strip these display characters before counting digits. They're
# common in formatted phone numbers (e.g. "+91 (98765) 43210") but
# carry no validation signal.
_PHONE_STRIP_RE = re.compile(r"[\s\-().]")

# Minimum and maximum digit counts. 7 = shortest reasonable national
# subscriber number; 15 = E.164 ceiling (1-3 country code + 1-12 nat'l).
_PHONE_MIN_DIGITS = 7
_PHONE_MAX_DIGITS = 15


def validate_phone_number(value: str) -> str:
    """Validate ``value`` as a phone number. Returns it stripped of
    leading/trailing whitespace on success; raises ``ValueError``
    otherwise.

    Used as a Pydantic ``field_validator`` (mode='before' or default).
    """
    if not isinstance(value, str):
        raise ValueError("phoneNumber must be a string.")
    s = value.strip()
    if not s:
        raise ValueError("phoneNumber cannot be empty.")

    # Drop spaces / hyphens / parens / dots — they're display only.
    cleaned = _PHONE_STRIP_RE.sub("", s)

    # Allow a single optional leading '+'.
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    else:
        digits = cleaned

    if not digits.isdigit():
        raise ValueError(
            "phoneNumber may only contain digits, with optional '+' "
            "country-code prefix and ' '/'-'/'('/')'/'.'/' separators."
        )

    n = len(digits)
    if n < _PHONE_MIN_DIGITS:
        raise ValueError(
            f"phoneNumber is too short — needs at least {_PHONE_MIN_DIGITS} "
            f"digits (got {n})."
        )
    if n > _PHONE_MAX_DIGITS:
        raise ValueError(
            f"phoneNumber is too long — at most {_PHONE_MAX_DIGITS} "
            f"digits allowed (got {n})."
        )
    return s
