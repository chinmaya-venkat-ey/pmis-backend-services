"""Division / DivisionOther pair validators for activities.

Mirrors the project-level owner / owner_other pattern at
``utilities/owner_pair.py`` but applies to two activity fields:

  * ``owner_division`` (single division code) + ``owner_division_other``
  * ``concerned_divisions`` (list of codes)  + ``concerned_division_other``

Rules:
  - When the code (or list) targets the catalog row ``'others'``, the
    companion text must be non-empty (1-255 chars).
  - When the code is anything else, the companion text MUST be empty/null.
  - The Sentinel value ``UNTOUCHED`` lets the PATCH path skip a side that
    wasn't supplied in the payload (so omitting a field means "no change").

Error messages are kept short and FE-facing; status code is the standard
422 ``ValidationError``.
"""
from __future__ import annotations

from typing import Any, List, Optional

from app.core.errors import ValidationError


# Sentinel — different from ``None`` because the wire-level None
# can mean "explicitly clear this field".
class _Untouched:
    __slots__ = ()
UNTOUCHED: Any = _Untouched()


_OTHERS = "others"


def _normalized(text: Optional[str]) -> str:
    return (text or "").strip()


def validate_owner_division_pair(
    *,
    owner_division: Any = UNTOUCHED,
    owner_division_other: Any = UNTOUCHED,
    existing_owner_division: Optional[str] = None,
    existing_owner_division_other: Optional[str] = None,
) -> None:
    """Validate the owner_division + owner_division_other pair.

    Pass ``UNTOUCHED`` for a side that wasn't supplied on PATCH so the
    existing DB value is used. Raises ``ValidationError`` (422) on the
    first violation.
    """
    effective_code = existing_owner_division if owner_division is UNTOUCHED else owner_division
    effective_other = existing_owner_division_other if owner_division_other is UNTOUCHED else owner_division_other

    code_norm = (effective_code or "").strip().lower() or None
    other_norm = _normalized(effective_other)
    is_others = code_norm == _OTHERS
    has_other = other_norm != ""

    if is_others:
        if not has_other:
            raise ValidationError(
                "ownerDivisionOther is required (non-empty) when "
                "ownerDivision is 'others'."
            )
        if len(other_norm) > 255:
            raise ValidationError(
                "ownerDivisionOther must be 1-255 characters."
            )
    elif code_norm is not None and has_other:
        raise ValidationError(
            "ownerDivisionOther may only be provided when "
            "ownerDivision is 'others'."
        )


def validate_concerned_divisions_pair(
    *,
    concerned_divisions: Any = UNTOUCHED,
    concerned_division_other: Any = UNTOUCHED,
    existing_concerned_divisions: Optional[List[str]] = None,
    existing_concerned_division_other: Optional[str] = None,
) -> None:
    """Validate the concerned_divisions list + concerned_division_other pair.

    Same UNTOUCHED-sentinel convention as ``validate_owner_division_pair``.
    """
    effective_list = (
        existing_concerned_divisions
        if concerned_divisions is UNTOUCHED
        else concerned_divisions
    )
    effective_other = (
        existing_concerned_division_other
        if concerned_division_other is UNTOUCHED
        else concerned_division_other
    )

    codes_norm = [
        (c or "").strip().lower()
        for c in (effective_list or [])
        if c is not None
    ]
    has_others = _OTHERS in codes_norm
    other_norm = _normalized(effective_other)
    has_other_text = other_norm != ""

    if has_others:
        if not has_other_text:
            raise ValidationError(
                "concernedDivisionOther is required (non-empty) when "
                "'others' appears in concernedDivisions."
            )
        if len(other_norm) > 255:
            raise ValidationError(
                "concernedDivisionOther must be 1-255 characters."
            )
    elif codes_norm and has_other_text:
        raise ValidationError(
            "concernedDivisionOther may only be provided when "
            "'others' appears in concernedDivisions."
        )
