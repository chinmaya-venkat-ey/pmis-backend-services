"""Shared guard: keep create-required fields from being cleared on update.

PATCH semantics: a field OMITTED from the body means "no change". A field
INCLUDED with an empty value (None / blank string / empty collection) means
"clear it" — which must be rejected so the create-time required-field
invariant also holds on the update paths (a direct API caller can't empty a
field the create gate insisted on).

Operates on the ``model_dump(exclude_unset=True)`` dict, so a key is present
ONLY when the caller actually sent it — omitted fields are never touched and
partial updates keep working unchanged.
"""
from __future__ import annotations

from typing import Mapping

from app.core.errors import ValidationError


def is_empty_value(value) -> bool:
    """True when a value counts as "cleared": None, a blank/whitespace-only
    string, or an empty list/tuple/set/dict."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def assert_required_not_cleared(
    updates: Mapping, required: Mapping[str, str], *, entity: str,
) -> None:
    """Raise 422 if any required field is present in ``updates`` but empty.

    ``updates`` is the ``model_dump(exclude_unset=True)`` dict (key present
    == the caller sent it). ``required`` maps the python field name -> the
    wire (camelCase) name used in the error message. Omitted fields are
    ignored (partial update = no change).
    """
    cleared = [
        wire for field, wire in required.items()
        if field in updates and is_empty_value(updates[field])
    ]
    if cleared:
        raise ValidationError(
            f"Cannot clear required field(s) on {entity} update: "
            f"{', '.join(cleared)}.",
            details={"cleared": cleared},
        )
