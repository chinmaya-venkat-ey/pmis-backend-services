"""Request schemas for the consolidated /api/v3/master/* endpoints (doc 20).

Each catalog has its own create + update body. Responses reuse the
existing per-catalog projection helpers in routes.py to keep the wire
format identical to the legacy endpoints.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Divisions
# ---------------------------------------------------------------------------

class DivisionCreateRequest(BaseModel):
    """POST /api/v3/master/divisions/create body.

    ``code`` is optional — when omitted, the service slugifies ``label``
    to derive one ('Engineering R&D' -> 'engineering_r_d'). Supply a
    code explicitly when you want a stable wire identifier independent
    of the human label.

    ``email`` and ``phoneNumber`` are REQUIRED (doc 36). Divisions own
    projects and need a routable contact channel. The seeded built-in
    rows (``tmd1`` / ``tmd2`` / ``others``) get default values backfilled
    from ``DIVISION_DEFAULT_EMAIL`` / ``DIVISION_DEFAULT_PHONE`` env
    vars at first boot.

    Built-in rows (``tmd1`` / ``tmd2`` / ``others``) cannot be created
    via this endpoint; the unique constraint on ``code`` rejects the
    insert with 409 if you try.
    """
    model_config = ConfigDict(populate_by_name=True)

    label: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(
        None, max_length=64,
        description=(
            "Optional. Lowercase alphanumeric + underscore. Derived from "
            "label via slugify when omitted."
        ),
    )
    requires_other: bool = Field(
        False, alias="requiresOther",
        description=(
            "True only on rows that prompt the FE to show a free-text "
            "follow-up input (the 'others' row uses this)."
        ),
    )
    email: EmailStr = Field(
        ...,
        description=(
            "Contact email for the division (e.g. a shared mailbox "
            "alias). RFC-5322-validated. **Required (doc 36).**"
        ),
    )
    phoneNumber: str = Field(
        ...,
        alias="phone_number",
        min_length=1,
        max_length=50,
        description=(
            "Contact phone for the division. Free-form (no regex) — "
            "same convention as vendors.phone_number. **Required (doc 36).**"
        ),
    )


class DivisionUpdateRequest(BaseModel):
    """PATCH /api/v3/master/divisions/{code} body.

    ``code`` itself is NOT patchable — it's the wire identifier that
    every project's ``owner`` column points at. Renaming would break
    every existing reference. Only ``label`` / ``requiresOther`` /
    ``email`` / ``phoneNumber`` are editable. Built-in rows accept patches
    only on ``email`` + ``phoneNumber`` (admins can still update contact
    details on the seeded rows); the route layer rejects label /
    requiresOther changes on built-ins with 403.

    Doc 36: ``email`` and ``phoneNumber`` are NOT NULL on the column,
    so empty-string-as-clear is no longer accepted on PATCH. Omit the
    field entirely to leave the existing value alone — standard PATCH
    semantics. Sending an empty string returns 422.
    """
    model_config = ConfigDict(populate_by_name=True)

    label: Optional[str] = Field(None, min_length=1, max_length=255)
    requires_other: Optional[bool] = Field(None, alias="requiresOther")
    email: Optional[EmailStr] = Field(
        None,
        description=(
            "New contact email. RFC-5322-validated. Cannot be cleared "
            "(column is NOT NULL post-doc-36)."
        ),
    )
    phoneNumber: Optional[str] = Field(
        None,
        alias="phone_number",
        min_length=1,
        max_length=50,
        description=(
            "New contact phone. Cannot be cleared (column is NOT NULL "
            "post-doc-36)."
        ),
    )


# ---------------------------------------------------------------------------
# Project status transitions
# ---------------------------------------------------------------------------

class ProjectStatusTransitionCreateRequest(BaseModel):
    """POST /api/v3/master/project_status_transitions/create body.

    Adds a new ``(from_status, to_status)`` edge to the project lifecycle.
    ``from_status=None`` represents the initial-status seed (state the
    system accepts on a fresh create).
    """
    model_config = ConfigDict(populate_by_name=True)

    from_status: Optional[str] = Field(
        None, alias="fromStatus", max_length=50,
        description="Source status; null marks an initial-status seed row.",
    )
    to_status: str = Field(..., alias="toStatus", min_length=1, max_length=50)
    requires_admin: bool = Field(False, alias="requiresAdmin")
    description: Optional[str] = Field(None, max_length=500)


class ProjectStatusTransitionUpdateRequest(BaseModel):
    """PATCH /api/v3/master/project_status_transitions/{id} body.

    Only the policy fields (requiresAdmin, description) are editable.
    The (from_status, to_status) tuple is the row's identity — patching
    it would amount to deleting one edge and creating another. Use
    DELETE + POST for that.
    """
    model_config = ConfigDict(populate_by_name=True)

    requires_admin: Optional[bool] = Field(None, alias="requiresAdmin")
    description: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Resource types
# ---------------------------------------------------------------------------

class ResourceTypeCreateRequest(BaseModel):
    """POST /api/v3/master/resource_types/create body."""
    model_config = ConfigDict(populate_by_name=True)
    code: str = Field(
        ..., min_length=1, max_length=50,
        description="Canonical lowercase code; unique across the catalog.",
    )
    name: str = Field(..., min_length=1, max_length=255)
    active: bool = Field(True)


class ResourceTypeUpdateRequest(BaseModel):
    """PATCH /api/v3/master/resource_types/{id} body.

    Only ``name`` is patchable. ``code`` is NOT updatable — every
    activity_resource row in the system points at the row's id, but the
    picker dropdown is keyed by code; renaming a code mid-flight would
    break consistency for resource activities created with the old
    code. Renames go through deactivate-and-create-new.
    """
    model_config = ConfigDict(populate_by_name=True)
    name: Optional[str] = Field(None, min_length=1, max_length=255)


# ---------------------------------------------------------------------------
# Doc 37 part 1 — static-data master schemas
# ---------------------------------------------------------------------------
#
# Four catalogs (project_categories, activity_types, milestone_statuses,
# activity_statuses). Same CRUD shape, minor field-set differences:
# project_categories carries a ``requiresOther`` flag (mirrors
# divisions); milestone/activity statuses carry an ``isTerminal`` flag.
# Activity types have neither.

class _CatalogCreateBase(BaseModel):
    """Shared shape for the four doc-37-part-1 catalog create requests."""
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(
        ..., min_length=1, max_length=50,
        description=(
            "Wire identifier; lowercase recommended for status/type "
            "rows, mixed case allowed for project_categories where "
            "MSAP/MSIP/BSP follow upstream conventions. Unique."
        ),
    )
    label: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    active: bool = Field(True)


class _CatalogUpdateBase(BaseModel):
    """Shared PATCH shape — only label / description / active editable.

    ``code`` is NEVER updatable: it's the wire identifier referenced by
    every record using this category / type / status. Renames go
    through soft-deactivate + create-new.
    """
    model_config = ConfigDict(populate_by_name=True)

    label: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    active: Optional[bool] = None


class ProjectCategoryCreateRequest(_CatalogCreateBase):
    requires_other: bool = Field(
        False, alias="requiresOther",
        description=(
            "True only on rows that prompt the FE to show "
            "categoryOther + categoryOtherReason follow-up inputs. "
            "Mirrors the divisions pattern."
        ),
    )


class ProjectCategoryUpdateRequest(_CatalogUpdateBase):
    requires_other: Optional[bool] = Field(None, alias="requiresOther")


class ActivityTypeCreateRequest(_CatalogCreateBase):
    pass


class ActivityTypeUpdateRequest(_CatalogUpdateBase):
    pass


class MilestoneStatusCreateRequest(_CatalogCreateBase):
    is_terminal: bool = Field(
        False, alias="isTerminal",
        description=(
            "Terminal status — rows that satisfy the dependency-"
            "completion gate. Today only 'completed' is terminal."
        ),
    )


class MilestoneStatusUpdateRequest(_CatalogUpdateBase):
    is_terminal: Optional[bool] = Field(None, alias="isTerminal")


class ActivityStatusCreateRequest(_CatalogCreateBase):
    is_terminal: bool = Field(False, alias="isTerminal")


class ActivityStatusUpdateRequest(_CatalogUpdateBase):
    is_terminal: Optional[bool] = Field(None, alias="isTerminal")


# ---------------------------------------------------------------------------
# Priorities (doc 41) — own create/update shape because the column is
# called ``name`` (not ``label`` like the rest of the catalogs).
# ---------------------------------------------------------------------------

class PriorityCreateRequest(BaseModel):
    """POST /api/v3/master/priorities."""
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(
        ..., min_length=1, max_length=16,
        description="Wire identifier (e.g. ``p1``, ``p2``, ``p3``). Unique.",
    )
    name: str = Field(
        ..., min_length=1, max_length=64,
        description="Label shown in the dropdown (e.g. ``p1``).",
    )
    description: Optional[str] = Field(None, max_length=500)
    position: Optional[int] = Field(None, ge=0)
    active: bool = Field(True)


class PriorityUpdateRequest(BaseModel):
    """PATCH /api/v3/master/priorities/{code}.

    ``code`` is never updatable — same rule as the rest of the
    catalogs (it's the wire identifier referenced from
    ``activities.priority``).
    """
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=64)
    description: Optional[str] = Field(None, max_length=500)
    position: Optional[int] = Field(None, ge=0)
    active: Optional[bool] = None

