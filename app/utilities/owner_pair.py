"""Owner / OwnerOther pair validator.

Matches the monolith's ``app/api/v3/projects/services/transitions.py::
validate_owner_pair`` semantics:

  * ``owner`` is a division code (``tmd1`` / ``tmd2`` / ``others`` plus any
    admin-added rows in ``masters.divisions``).
  * When ``owner == 'others'``: ``owner_other`` is required (non-empty,
    max 255 chars) — free-text label of the actual division.
  * When ``owner != 'others'``: ``owner_other`` MUST be empty.
  * ``require_owner=True`` (create flow) rejects an empty owner.
  * Error messages quoted verbatim from the monolith so the FE renders
    the same strings users have always seen.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.utilities.catalogs import (
    OWNER_DIVISION_CHOICES,
    active_owner_divisions,
    is_known_owner_division,
)


def normalize_owner_value(v: Optional[str]) -> Optional[str]:
    """Trim + lowercase the owner code. ``None``/empty pass through."""
    if v is None:
        return None
    cleaned = str(v).strip().lower()
    return cleaned or None


def validate_owner_pair(
    db: Session,
    *,
    owner: Optional[str],
    owner_other: Optional[str],
    require_owner: bool,
) -> None:
    """Apply the four owner-pair rules. Raises ``ValidationError`` (HTTP
    422) on the first violation. Error messages match the monolith
    byte-for-byte.

    ``require_owner=True`` on the create / upsert paths (owner is
    mandatory). ``False`` on the update path (omission = no-change).
    """
    n_owner = normalize_owner_value(owner)
    n_owner_other = (owner_other or "").strip() if owner_other is not None else None

    # 1. Owner required on create (when require_owner=True).
    if require_owner and not n_owner:
        raise ValidationError(
            f"Owner is required. Must be one of: "
            f"{sorted(OWNER_DIVISION_CHOICES)}."
        )

    # 2. Owner — when supplied — must be a known division code.
    if n_owner is not None and not is_known_owner_division(db, n_owner):
        raise ValidationError(
            f"Owner '{n_owner}' is not a known division. Pick one "
            f"from GET /divisions or use 'others' with a custom "
            f"ownerOther label."
        )

    # 3 & 4. Rules around ``owner_other``.
    is_others = (n_owner == "others")
    has_other = n_owner_other is not None and n_owner_other != ""

    if is_others:
        if not has_other:  # NOSONAR(S1066): nested structure groups owner=='others' rules
            raise ValidationError(
                "ownerOther is required (non-empty) when owner is 'others'."
            )
        if len(n_owner_other) > 255:
            raise ValidationError(
                "ownerOther must be 1-255 characters."
            )
    elif n_owner is not None and has_other:
        # Owner present (and not 'others') but ownerOther supplied — reject.
        raise ValidationError(
            "ownerOther may only be provided when owner is 'others'."
        )


def _assert_category_is_known(db: Session, n_category: str) -> None:
    from app.utilities.catalogs import is_known_project_category
    if not is_known_project_category(db, n_category):
        raise ValidationError(
            f"Invalid category '{n_category}'."
        )


def _assert_category_others_extras_present_and_valid(
    n_other: Optional[str], n_reason: Optional[str],
) -> None:
    """When category == 'others', BOTH ``categoryOther`` and
    ``categoryOtherReason`` are required + length-bounded."""
    if not n_other:
        raise ValidationError(
            "categoryOther is required when category is 'others'."
        )
    if len(n_other) > 255:
        raise ValidationError(
            "categoryOther must be 1-255 characters."
        )
    if not n_reason:
        raise ValidationError(
            "categoryOtherReason is required when category is 'others'."
        )
    if len(n_reason) > 1000:
        raise ValidationError(
            "categoryOtherReason must be 1-1000 characters."
        )


def _reject_category_extras_when_not_others(
    n_other: Optional[str], n_reason: Optional[str],
) -> None:
    """When category != 'others', neither ``categoryOther`` nor
    ``categoryOtherReason`` may be supplied."""
    if n_other:
        raise ValidationError(
            "categoryOther may only be provided when category is 'others'."
        )
    if n_reason:
        raise ValidationError(
            "categoryOtherReason may only be provided when category is 'others'."
        )


def validate_category_pair(
    db: Session,
    *,
    category: Optional[str],
    category_other: Optional[str],
    category_other_reason: Optional[str],
) -> None:
    """Apply the same coupling rules to category / categoryOther /
    categoryOtherReason (matches monolith's create.py:91-147).

    Doc-38 deprecated the category fields on the create / update wire
    but the DB columns are still populated when a request carries them
    so legacy callers continue to work. The validation kicks in only
    when the caller actually supplies the fields.

    Check order preserved: (a) catalog lookup, then (b) per-branch
    coupling rules. First violation wins, so user-facing messages are
    byte-identical to the legacy in-line form.
    """
    # Category codes are case-SENSITIVE in the monolith — MSAP/MSIP/BSP are
    # stored UPPERCASE; only 'others' is lowercase. Don't fold the case here
    # or the catalog lookup misses every legit code.
    n_category = (category or "").strip() if category is not None else None
    n_other = (category_other or "").strip() if category_other is not None else None
    n_reason = (
        (category_other_reason or "").strip()
        if category_other_reason is not None else None
    )

    if not n_category:
        return

    _assert_category_is_known(db, n_category)

    if n_category == "others":
        _assert_category_others_extras_present_and_valid(n_other, n_reason)
    else:
        _reject_category_extras_when_not_others(n_other, n_reason)
