"""Vendor token resolution + existence / active check.

The monolith accepts vendor identifiers in TWO forms (Doc-25):

  * UUID:                  ``"b434fb20-5fb7-4f62-a455-685952077f16"``
  * Human-readable code:   ``"VN-ACME-260516120000"`` (the
                            ``masters.vendors.vendor_code`` column)

This helper resolves each token to its canonical UUID (via the
cross-schema ``masters.vendors`` mirror), de-duplicates, and validates
that every resolved id maps to an active, non-soft-deleted row. Matches
``app/infrastructure/db/repositories/vendor_repository.py::resolve_id``
and ``existing_active_ids`` in the monolith.

Error messages quoted verbatim from the monolith so the FE renders the
same strings.
"""
from __future__ import annotations

from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.models._cross_schema import Vendor as _VendorMirror


def _looks_like_vendor_code(token: str) -> bool:
    """Heuristic: VN-prefixed strings are codes. UUID format detection is
    overkill — anything not VN-prefixed is treated as a candidate UUID
    and the existence check catches typos."""
    return token.strip().upper().startswith("VN-")


def _dedup_trim_tokens(tokens: List[str]) -> List[str]:
    """De-dup preserving order; trim whitespace; drop empties."""
    seen: dict[str, None] = {}
    cleaned: List[str] = []
    for t in tokens:
        if not t:
            continue
        s = str(t).strip()
        if s and s not in seen:
            seen[s] = None
            cleaned.append(s)
    return cleaned


def _resolve_codes_to_uuids(
    db: Session, code_tokens: List[str],
) -> dict:
    """Look up vendor_code → id for every VN-prefixed token. Raises
    ``ValidationError`` if any code doesn't resolve."""
    code_to_uuid: dict = {}
    if code_tokens:
        rows = db.execute(
            select(_VendorMirror.vendor_code, _VendorMirror.id)
            .where(_VendorMirror.vendor_code.in_(code_tokens))
            .where(_VendorMirror.deleted_at.is_(None))
        ).all()
        code_to_uuid = dict(rows)

    unresolved = [t for t in code_tokens if t not in code_to_uuid]
    if unresolved:
        raise ValidationError(
            f"Unknown vendor(s): {', '.join(unresolved)}"
        )
    return code_to_uuid


def _build_canonical(
    cleaned: List[str], code_to_uuid: dict,
) -> Tuple[List[str], dict]:
    """Map each cleaned token to its canonical UUID, preserving caller
    order. Returns ``(canonical_list, canonical_to_input)`` where the
    second is used for friendlier error messages downstream."""
    canonical: List[str] = []
    canonical_to_input: dict = {}
    for t in cleaned:
        cid = code_to_uuid[t] if _looks_like_vendor_code(t) else t
        canonical.append(cid)
        canonical_to_input.setdefault(cid, t)
    return canonical, canonical_to_input


def _assert_canonical_uuids_live(
    db: Session, canonical: List[str], canonical_to_input: dict,
) -> None:
    """Verify every canonical UUID exists as an active, non-soft-deleted
    row. Raises ``ValidationError`` listing the original input tokens
    that failed."""
    rows = db.execute(
        select(_VendorMirror.id)
        .where(_VendorMirror.id.in_(canonical))
        .where(_VendorMirror.active.is_(True))
        .where(_VendorMirror.deleted_at.is_(None))
    ).all()
    live_ids = {r[0] for r in rows}
    missing = [
        canonical_to_input[cid] for cid in canonical if cid not in live_ids
    ]
    if missing:
        raise ValidationError(
            f"Unknown or inactive vendor(s): {', '.join(missing)}"
        )


def resolve_and_validate_vendor_ids(
    db: Session, tokens: List[str],
) -> List[str]:
    """Take a mixed list of UUIDs / vendor codes and return canonical
    UUIDs in caller-supplied order, de-duplicated.

    Raises ``ValidationError`` (HTTP 422):
      * ``"Unknown vendor(s): {tokens}"`` when a code can't be resolved.
      * ``"Unknown or inactive vendor(s): {tokens}"`` when a resolved
        UUID doesn't exist as an active, live row.

    Caller still has to check vendor-in-project for activity / milestone
    vendor mappings — that's a separate guard (see
    ``vendor_in_project`` below).

    Error message order preserved: code-resolution failure raises first,
    then live/active check.
    """
    if not tokens:
        return []

    cleaned = _dedup_trim_tokens(tokens)
    if not cleaned:
        return []

    code_tokens = [t for t in cleaned if _looks_like_vendor_code(t)]
    code_to_uuid = _resolve_codes_to_uuids(db, code_tokens)
    canonical, canonical_to_input = _build_canonical(cleaned, code_to_uuid)

    if canonical:
        _assert_canonical_uuids_live(db, canonical, canonical_to_input)

    return canonical


def assert_vendor_in_project(
    db: Session, *, project_id: str, vendor_id: str,
) -> None:
    """Activity / milestone vendor must already be attached to the
    parent project (monolith parity — see
    PMIS-OpenProject/app/api/v3/activities/services/create.py:101-116)."""
    from app.models.project_vendor import ProjectVendor
    found = db.execute(
        select(ProjectVendor.vendor_id)
        .where(ProjectVendor.project_id == project_id)
        .where(ProjectVendor.vendor_id == vendor_id)
        .limit(1)
    ).first()
    if found is None:
        raise ValidationError(
            f"vendorId '{vendor_id}' is not in the project's vendor list. "
            f"Add the vendor to the project before assigning it to an activity."
        )
