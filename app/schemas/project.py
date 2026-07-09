"""Project schemas — request / response models for /project/projects/*.

Wire convention (matches monolith):
  * Request bodies accept BOTH camelCase aliases AND snake_case field
    names — ``alias_generator=to_camel`` + ``populate_by_name=True``. So
    ``startDate`` and ``start_date`` are both valid, and the FE can keep
    sending its existing camelCase payloads.
  * Response bodies camelize at the HAL wrapper layer (see
    ``app.core.api_route._camelize``) so every key on the wire ends up
    camelCase regardless of the Pydantic field name.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel
from app.schemas.attachment import AttachmentRow


# Monolith parity: schema-level status validation uses this hardcoded
# 4-value fallback (matches PMIS-OpenProject/.../transitions.py:
# PROJECT_STATUS_CHOICES). Service-level transition validation (uses the
# full ``masters.project_status_transitions`` catalog) only fires on PATCH.
_PROJECT_STATUS_CHOICES = ("new", "draft", "published", "closed")
_ERR_END_BEFORE_START = "end_date cannot be before start_date"


# ---------------------------------------------------------------------------
# Shared config for request bodies — accept camelCase OR snake_case.
# ---------------------------------------------------------------------------

_REQUEST_CONFIG = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class _VendorChip(BaseModel):
    """Slim vendor object embedded on the project response — matches the
    monolith's ``vendors[]`` shape (``{id, name}``) so the FE renders
    organisation chips without a per-id round-trip. Monolith parity: no
    ``active`` field on the chip."""

    model_config = ConfigDict(from_attributes=False)
    id: str
    name: Optional[str] = None


class ProjectConfig(BaseModel):
    """Project-specific config/checks bag (see ``Project.config``).

    A grouped object of per-project values that are NOT driven by any master
    catalog. The known checks are typed below; **unknown keys are preserved**
    (``extra="allow"``) so new checks can be added over time without a schema
    change. Every field is optional. Accepts camelCase OR snake_case on write;
    camelizes on the wire (HAL layer) on read.

    Known checks:
      * ``half_day_hours`` — definition of a half day, in hours (e.g. 4).
      * ``attendance_captured`` — whether attendance is captured for the project.
      * ``sandwich_leave_applied`` — whether the sandwich-leave policy applies
        (the calendar-date evaluation is a downstream concern; this is the flag).
      * ``leaves_per_frequency_count`` + ``leaves_frequency`` — how many leave
        days are granted per period, and the period (e.g. 2 per ``"quarterly"``).
      * ``prorated_leaves_applied`` — whether leaves are prorated.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="allow",
    )

    half_day_hours: Annotated[Optional[Decimal], Field(default=None, ge=0, le=24)] = None
    attendance_captured: Optional[bool] = None
    sandwich_leave_applied: Optional[bool] = None
    leaves_per_frequency_count: Annotated[Optional[int], Field(default=None, ge=0)] = None
    leaves_frequency: Annotated[Optional[str], Field(default=None, max_length=32)] = None
    prorated_leaves_applied: Optional[bool] = None


class ProjectResponse(ResponseModel):
    # Field order matches monolith ``format_project_response`` byte-for-byte:
    # id, projectCode, name, description, active, public, isPublic,
    # statusExplanation, status, owner, ownerOther, category,
    # categoryOther, categoryOtherReason, vendors, startDate, endDate,
    # actualStartDate, actualEndDate, parentId, createdBy, updatedBy,
    # createdAt, updatedAt, deletedAt, deletedBy.
    id: str
    project_code: str
    name: str
    description: Optional[str] = None
    active: bool
    public: bool
    is_public: bool = False
    status_explanation: Optional[str] = None

    status: str
    owner: Optional[str] = None
    # Human-readable label of the owner division (resolved from masters.divisions).
    # Null when owner is None or an unknown code. Lets the FE render
    # the project owner column without a separate /master/divisions call.
    owner_label: Optional[str] = None
    category: Optional[str] = None
    category_other: Optional[str] = None
    category_other_reason: Optional[str] = None

    vendors: List[_VendorChip] = Field(default_factory=list)

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None

    parent_id: Optional[str] = None

    # Finance fields (Doc-finance). All three are returned on every project
    # response — they're stored with safe defaults (0 / 0 / 25) on existing
    # rows so the response shape stays consistent.
    # ``total_project_value_incl_tax`` is computed in the controller from
    # the excl-tax value × (1 + tax_percent/100) and is read-only here.
    total_project_value_excl_tax: Optional[Decimal] = None
    tax_percent: Optional[Decimal] = None
    total_project_value_incl_tax: Optional[Decimal] = None
    ccn_cap_percent: Optional[Decimal] = None

    # Project-specific config/checks bag — grouped into ONE object and returned
    # on every project response so the FE can read all per-project settings
    # (half-day hours, attendance/leave policy flags, etc.) without a separate
    # call. Set via ``PUT /projects/{uuid}/config``. Defaults to {} for rows
    # that never configured it.
    config: ProjectConfig = Field(default_factory=ProjectConfig)

    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None

    # 2026-06-03 — id of the hidden meeting milestone for this project.
    # Populated on every project response for published projects (created
    # on publish, or just-in-time on detail fetch for projects that
    # predate the feature). Null for pre-publish projects. FE creates
    # meeting-type activities by POSTing to
    # ``/milestones/{meetingMilestoneId}/activities/create``. The
    # milestone itself is filtered out of every milestone-level surface
    # (list, dashboards, CPM, discussion feed).
    meeting_milestone_id: Optional[str] = None

    # Monolith parity: ``attachments`` is included ONLY on the GET
    # single-project response. Create / update / upsert / save / publish
    # / close responses + every list element OMIT this field entirely.
    # Controller populates it on ``get()``; HAL wrap layer drops the key
    # when its value is None so other endpoints don't leak ``"attachments": null``.
    attachments: Optional[List[AttachmentRow]] = None


# ---------------------------------------------------------------------------
# Create / Update / Upsert / Close
# ---------------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    """POST /project/projects/create body — JSON arm of the dual-mode endpoint.

    Accepts both camelCase aliases (``vendorIds``, ``startDate``,
    ``statusExplanation``, ``parentId``, ``ownerOther``) and snake_case
    field names. On the multipart arm the same fields arrive as form
    values; ``vendor_ids`` is JSON-encoded inside multipart so it can
    carry an array.
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    active: bool = True
    public: bool = False
    status_explanation: Annotated[Optional[str], Field(default=None, max_length=5000)]
    parent_id: Annotated[Optional[str], Field(default=None, max_length=36)]

    # Monolith parity: status defaults to "new" on create/upsert.
    status: Annotated[Optional[str], Field(default="new", max_length=50)]
    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    category: Annotated[Optional[str], Field(default=None, max_length=50)]
    category_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category_other_reason: Annotated[Optional[str], Field(default=None, max_length=1000)]

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    vendor_ids: List[str] = Field(default_factory=list)

    # Finance fields (Doc-finance) — all optional. When omitted, the DB
    # server defaults (0 / 0 / 25) apply. Existing FE clients that don't
    # send these fields keep working unchanged.
    total_project_value_excl_tax: Annotated[
        Optional[Decimal], Field(default=None, ge=0)
    ] = None
    tax_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None
    ccn_cap_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None

    # Monolith parity: schema-level status validator with the 4-value
    # fallback. Raw FastAPI ``{"detail": [...]}`` error shape on failure.
    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if v not in _PROJECT_STATUS_CHOICES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {', '.join(_PROJECT_STATUS_CHOICES)}"
            )
        return v

    # Monolith parity: schema-level end-date check as a FIELD validator
    # (matches monolith ``@field_validator("end_date")``) so the
    # RequestValidationError's ``loc`` is ``["endDate"]`` and ``input``
    # is just the bad value — not the whole request body.
    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError(_ERR_END_BEFORE_START)
        return v


class ProjectUpdateRequest(BaseModel):
    """PATCH /project/projects/{uuid} body — partial update.

    Same camelCase / snake_case dual acceptance as Create. ``active``,
    ``status``, and ``parent_id`` are settable here (matches monolith's
    ``ProjectUpdateRequest`` — see PMIS-OpenProject/app/api/v3/projects/
    schemas.py:104).
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    active: Optional[bool] = None
    public: Optional[bool] = None
    status_explanation: Annotated[Optional[str], Field(default=None, max_length=5000)]
    parent_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    # Monolith parity: status defaults to "new" on create/upsert.
    status: Annotated[Optional[str], Field(default="new", max_length=50)]
    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    vendor_ids: Optional[List[str]] = None

    # Finance fields (Doc-finance) — optional on PATCH. Editing finance via
    # ``PATCH /projects/{uuid}/update`` is intentionally allowed only for
    # backwards compatibility with the standard project update path; the
    # canonical entry point is ``PATCH /projects/{uuid}/finance`` which
    # carries the publish-lock + finance-field RBAC gate. The service
    # layer here applies the same publish-lock when finance fields are
    # touched via the generic update route.
    total_project_value_excl_tax: Annotated[
        Optional[Decimal], Field(default=None, ge=0)
    ] = None
    tax_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None
    ccn_cap_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError(_ERR_END_BEFORE_START)
        return v


class ProjectUpsertRequest(BaseModel):
    """PUT /project/projects/{uuid} body — idempotent create-or-update.

    Same camelCase / snake_case dual acceptance. On first submission the
    row is inserted (201); subsequent submissions update it (200) and
    the response body carries ``_created: false`` so the FE can tell.
    The server auto-generates ``project_code`` on insert and preserves
    it on update.
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    active: bool = True
    public: bool = False
    status_explanation: Annotated[Optional[str], Field(default=None, max_length=5000)]
    parent_id: Annotated[Optional[str], Field(default=None, max_length=36)]

    # Monolith parity: status defaults to "new" on create/upsert.
    status: Annotated[Optional[str], Field(default="new", max_length=50)]
    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    category: Annotated[Optional[str], Field(default=None, max_length=50)]
    category_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category_other_reason: Annotated[Optional[str], Field(default=None, max_length=1000)]

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    vendor_ids: Optional[List[str]] = None

    # Finance fields — optional on UPSERT. Same rules as Create/Update.
    total_project_value_excl_tax: Annotated[
        Optional[Decimal], Field(default=None, ge=0)
    ] = None
    tax_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None
    ccn_cap_percent: Annotated[
        Optional[Decimal], Field(default=None, ge=0, le=100)
    ] = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if v not in _PROJECT_STATUS_CHOICES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {', '.join(_PROJECT_STATUS_CHOICES)}"
            )
        return v

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError(_ERR_END_BEFORE_START)
        return v


class ProjectCloseRequest(BaseModel):
    """Optional body for POST /project/projects/{uuid}/close."""

    model_config = _REQUEST_CONFIG
    reason: Annotated[Optional[str], Field(default=None, max_length=5000)]
