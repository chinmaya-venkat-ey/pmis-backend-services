"""Activity API schemas.

Doc 38: ``type`` (standard / resource / transactional) and the resource
block (``resourceMode`` / ``resourceCount`` / ``resource``) are
deprecated and were dropped from both create and update wire bodies.
DB columns kept for legacy reads. Single create endpoint:
``POST /milestones/{id}/activities/create``.

Doc 39:
- Ownership fields ``ownerDivision`` / ``vendorId`` /
  ``concernedDivision`` are REQUIRED on create.
- ``concernedDivision`` keyword is preserved for FE compatibility; only
  the *datatype* changed from string to list of division codes
  (``["tmd1", "others"]``). Backed on disk by the new
  ``concerned_divisions`` JSON column; the legacy single-value
  ``concerned_division`` column is kept untouched for safety.

Doc 39 follow-up (concernedDivision free-text on "others"):
- ``concernedDivision`` list elements now accept free-text values in
  addition to the catalog codes. The FE picker shows the catalog
  (``tmd1`` / ``tmd2`` / ``others``) plus an "Other" option that
  reveals a text input; the typed value is sent inline as a list
  element, matching the project-vendors multi-add idiom. Example:
  ``["tmd1", "other admin"]``.
- Catalog codes are still normalized to lowercase. Free-text values
  pass through (whitespace stripped) so FE controls the display
  casing. Per-entry length 1..64; per-list size 1..20; case-insensitive
  dedup preserves the first occurrence.
- ``ownerDivision`` is intentionally NOT relaxed — it's a single value
  and stays strict against the catalog. Only the multi-value
  concerned-division list takes free text.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ....shared.datetime import IstCalendarDate
from ....domain.activities.activity import ACTIVITY_STATUS_CHOICES
from ....domain.priorities.priority import PRIORITY_CHOICES
from ....domain.resource_types.resource_type import DIVISION_CHOICES


_CONCERNED_ENTRY_MAX = 64
_CONCERNED_LIST_MAX = 20


def _validate_division_code(v: str) -> str:
    """Strict catalog check — used by ``ownerDivision`` (single value)."""
    if isinstance(v, str):
        v = v.strip().lower()
    if v not in DIVISION_CHOICES:
        raise ValueError(
            f"Division code must be one of: {', '.join(DIVISION_CHOICES)}."
        )
    return v


def _validate_concerned_entry(v) -> str:
    """Loose check — used per-entry inside ``concernedDivision`` list.

    Accepts either a known catalog code (``tmd1`` / ``tmd2`` / ``others``)
    or a free-text label typed by the user under the "Other" picker
    branch. Catalog codes are lowercased; free text is passed through
    after ``.strip()`` so FE controls the display casing.
    """
    if not isinstance(v, str):
        raise ValueError("Each concernedDivision entry must be a string.")
    s = v.strip()
    if not s:
        raise ValueError("concernedDivision entries cannot be blank.")
    if len(s) > _CONCERNED_ENTRY_MAX:
        raise ValueError(
            f"concernedDivision entry must be {_CONCERNED_ENTRY_MAX} "
            f"characters or fewer."
        )
    if s.lower() in DIVISION_CHOICES:
        return s.lower()
    return s


def _normalize_concerned_list(items: List[str]) -> List[str]:
    """Apply per-entry validation, dedup case-insensitively, enforce list cap."""
    cleaned: List[str] = []
    seen = set()
    for raw in items:
        entry = _validate_concerned_entry(raw)
        key = entry.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(entry)
    if len(cleaned) > _CONCERNED_LIST_MAX:
        raise ValueError(
            f"concernedDivision accepts at most {_CONCERNED_LIST_MAX} "
            f"entries."
        )
    return cleaned


class ActivityCreateRequest(BaseModel):
    """POST /milestones/{milestone_id}/activities/create.

    Unified shape: same superset of fields as PATCH. Required fields
    stay required (name + dates + ownership trio); everything else is
    optional and falls back to a sensible default on omission.
    ``status`` / ``actualStartDate`` / ``actualEndDate`` / ``dependsOn``
    can all be supplied at creation time when the FE has them, or
    deferred to PATCH after the row exists.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization.
    start_date: IstCalendarDate = Field(..., alias="startDate")
    end_date: IstCalendarDate = Field(..., alias="endDate")
    actual_start_date: Optional[IstCalendarDate] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[IstCalendarDate] = Field(None, alias="actualEndDate")
    position: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    depends_on: Optional[List[str]] = Field(None, alias="dependsOn")

    # Doc 39 mandatory ownership fields.
    owner_division: str = Field(
        ..., alias="ownerDivision", min_length=1,
        description=f"Division code. One of: {', '.join(DIVISION_CHOICES)}.",
    )
    vendor_id: str = Field(
        ..., alias="vendorId", min_length=1,
        description=(
            "Vendor UUID. Must be one of the project's vendors — "
            "service-side check rejects a vendor that's not in the "
            "project's vendor list."
        ),
    )
    # Doc 39: wire keyword kept as ``concernedDivision`` (singular) for FE
    # backwards compatibility — only the *datatype* changed from string to
    # list. The Python attribute is plural to match the new JSON DB column.
    concerned_divisions: List[str] = Field(
        ..., alias="concernedDivision", min_length=1,
        description=(
            "List of division values — at least one required, at most "
            f"{_CONCERNED_LIST_MAX}. Each entry is either a catalog code "
            f"({', '.join(DIVISION_CHOICES)}) or a free-text label (max "
            f"{_CONCERNED_ENTRY_MAX} chars) typed under the picker's "
            "\"Other\" branch. Case-insensitive dedup."
        ),
    )
    # Doc 41: priority code — REQUIRED on create. The wire string is
    # validated against the in-code fallback here (cheap), and the
    # service layer re-validates against the live DB catalog so
    # admin-added codes (p4, p5, …) are also accepted.
    priority: str = Field(
        ..., min_length=1, max_length=16,
        description=(
            "Priority code from the priorities catalog. Built-in codes: "
            f"{', '.join(PRIORITY_CHOICES)}. Admins can add more via "
            "POST /api/v3/master/priorities/create."
        ),
    )

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        s = info.data.get("start_date")
        if s is not None and v < s:
            raise ValueError("End date cannot be before the start date.")
        return v

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in ACTIVITY_STATUS_CHOICES:
            raise ValueError(
                f"Activity status must be one of: {', '.join(ACTIVITY_STATUS_CHOICES)}."
            )
        return v

    @field_validator("owner_division", mode="before")
    @classmethod
    def _validate_owner(cls, v):
        return _validate_division_code(v)

    @field_validator("concerned_divisions", mode="before")
    @classmethod
    def _validate_concerned(cls, v):
        if not isinstance(v, list):
            raise ValueError("concernedDivision must be a list.")
        return _normalize_concerned_list(v)

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        # Lowercase + strip; live catalog validation happens in the
        # service layer (so p4/p5 etc. added by an admin are accepted).
        if isinstance(v, str):
            v = v.strip().lower()
        return v


class ActivityUpdateRequest(BaseModel):
    """PATCH /activities/{id}. Partial update — doc 38 / 39 wire surface only.

    Legacy ``type`` / ``resourceMode`` / ``resourceCount`` / ``resource``
    and the single-valued ``concernedDivision`` were dropped from the
    wire (DB columns kept for read-side compat with legacy rows).

    ``dependsOn`` semantics: None = no change, [] = clear, [...] = replace.
    Same semantics for ``concernedDivision``.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization.
    start_date: Optional[IstCalendarDate] = Field(None, alias="startDate")
    end_date: Optional[IstCalendarDate] = Field(None, alias="endDate")
    actual_start_date: Optional[IstCalendarDate] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[IstCalendarDate] = Field(None, alias="actualEndDate")
    position: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    depends_on: Optional[List[str]] = Field(None, alias="dependsOn")

    # Doc 38 + 39 ownership fields (optional on PATCH; required on create).
    owner_division: Optional[str] = Field(None, alias="ownerDivision")
    vendor_id: Optional[str] = Field(None, alias="vendorId")
    concerned_divisions: Optional[List[str]] = Field(None, alias="concernedDivision")
    # Doc 41: priority code — optional on PATCH (None = no change).
    priority: Optional[str] = Field(None, max_length=16)

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in ACTIVITY_STATUS_CHOICES:
            raise ValueError(
                f"Activity status must be one of: {', '.join(ACTIVITY_STATUS_CHOICES)}."
            )
        return v

    @field_validator("owner_division", mode="before")
    @classmethod
    def _validate_owner(cls, v):
        if v is None:
            return v
        return _validate_division_code(v)

    @field_validator("concerned_divisions", mode="before")
    @classmethod
    def _validate_concerned(cls, v):
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("concernedDivision must be a list.")
        return _normalize_concerned_list(v)

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().lower()
        return v


class ActivityListQuery(BaseModel):
    offset: int = Field(1, ge=1)
    pageSize: int = Field(20, ge=1, le=100)
    includeDeleted: bool = Field(False)
