"""Activity schemas + activity-resource sub-schema."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel
from app.schemas.comment import CommentResponse
from app.utilities.date_rules import to_ist_calendar_date


# Shared config — accept camelCase aliases AND snake_case (monolith parity).
_REQUEST_CONFIG = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


# Monolith parity: schema-level status validation uses this 2-value
# hardcoded set on create + update (activities surface
# ``not_completed`` / ``completed`` only).
_ACTIVITY_STATUS_CHOICES = ("not_completed", "completed")

# Doc-finance category choices — same semantics as
# app/schemas/milestone.py:_M_A_CATEGORY_CHOICES.
_M_A_CATEGORY_CHOICES = ("original", "asg", "ccn")

# Resource classification for resource-based-milestone activities: whether the
# activity's resources are part of the original plan or brought in additionally.
_RESOURCE_CLASSIFICATION_CHOICES = ("planned", "additional")


class ActivityStartRequest(BaseModel):
    """#188 — POST /activities/{id}/start. Body optional; ``actualStartDate``
    defaults to now when omitted."""

    model_config = _REQUEST_CONFIG

    actual_start_date: Optional[datetime] = None


class ActivityResourceSchema(ResponseModel):
    """Embedded resource sidecar (1:1 with activity)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    resource_name: str
    onboard_date: Optional[datetime] = None
    actual_onboard_date: Optional[datetime] = None
    offboard_date: Optional[datetime] = None
    actual_offboard_date: Optional[datetime] = None
    position: Optional[str] = None
    designation: Optional[str] = None
    job_role: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[Decimal] = None
    type_of_resource_id: Optional[str] = None
    division: Optional[str] = None
    division_other: Optional[str] = None


class ActivityPlannedResourceItem(BaseModel):
    """One planned-resource allocation on a resource-based activity (create/update).

    ``designation`` is the leave-mgmt ``role`` name (the rate is resolved LIVE at
    compute time, never sent here). ``duration`` is a flat number of months in
    [0, 3]. ``planned_deployment_date`` is the calendar date this allocation is
    planned to deploy — one date per row (split across dates = separate rows).
    ``quantity``, ``duration`` and ``planned_deployment_date`` are all required."""

    model_config = _REQUEST_CONFIG

    designation: Annotated[str, Field(min_length=1, max_length=255)]
    quantity: Annotated[int, Field(ge=1)]
    duration: Annotated[Decimal, Field(ge=0, le=3)]
    planned_deployment_date: date

    @field_validator("planned_deployment_date", mode="before")
    @classmethod
    def _normalize_deployment_date(cls, v):
        """Guard: store the IST-local calendar day the user picked.

        A plain ``YYYY-MM-DD`` (what the FE sends) passes through unchanged;
        a client that serialises the date as a full instant (e.g. IST
        midnight as a UTC ``Z`` timestamp, which lands on the previous UTC
        day) is projected onto the IST calendar so the stored date never
        shifts by a timezone. See ``date_rules.to_ist_calendar_date``.
        """
        return to_ist_calendar_date(v)


class ActivityPlannedResourceResponse(ResponseModel):
    """One allocation row with its live-resolved monthly rate + computed cost."""

    designation: str
    quantity: int
    duration: Decimal
    planned_deployment_date: date  # required calendar date for this allocation row
    monthly_rate: Optional[Decimal] = None    # live from leave-mgmt (0 if unavailable)
    computed_cost: Optional[Decimal] = None   # quantity × monthlyRate × duration


class ActivityResponse(ResponseModel):
    """Field order matches monolith ``format_activity_response`` byte-for-byte:
    id, displayCode, projectId, milestoneId, name, description, type,
    ownerDivision, concernedDivision, vendorId, priority, startDate,
    endDate, actualStartDate, actualEndDate, position, resourceMode,
    resourceCount, status, dependsOn, dependsOnDisplay, createdAt,
    updatedAt, createdBy, updatedBy, deletedAt, resource.

    Wire NOTE: monolith uses the SINGULAR alias ``concernedDivision`` for
    the plural list field (FE back-compat). The Python attribute matches
    monolith convention (``concerned_division`` singular Python name
    holding a list) so the auto-camelize at the wrap layer produces
    ``concernedDivision`` on the wire.
    """
    id: str
    # Sequential per-milestone label like "A1.1" / "A1.2" — controller
    # populates from (milestone.position, activity.position).
    display_code: Optional[str] = None
    project_id: str
    milestone_id: str
    name: str
    description: Optional[str] = None
    type: Optional[str] = None
    owner_division: Optional[str] = None
    # Singular Python name → singular wire (``concernedDivision``).
    # Value is a list (Doc-39 multi-division).
    concerned_division: Optional[List[Any]] = None
    vendor_id: Optional[str] = None
    priority: Optional[str] = None
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    position: int
    resource_mode: Optional[str] = None
    resource_count: Optional[int] = None
    # 'planned' | 'additional' for resource-based-milestone activities; else null.
    resource_classification: Optional[str] = None
    status: Optional[str] = None
    activity_started: bool = False
    depends_on: List[str] = Field(default_factory=list)
    # UUIDs from depends_on resolved to display codes (e.g., ["A1.1"]).
    depends_on_display: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    resource: Optional[ActivityResourceSchema] = None
    # Per-activity planned-resource allocations (resource-based activities), each
    # with its live-resolved rate + cost; empty for non-resource activities.
    resources: List[ActivityPlannedResourceResponse] = Field(default_factory=list)
    resource_cost_total: Decimal = Decimal("0")
    # Category + CCN value (Doc-finance). See app/schemas/milestone.py.
    category: str = "original"
    ccn_value: Decimal = Decimal("0")
    # Inline first comment populated only on the multipart /create arm
    # when body/files are supplied. Dropped from the wire (by the camel
    # layer) when ``None``.
    comment: Optional[CommentResponse] = None


class CompletionBlocker(ResponseModel):
    """One dependency target that is blocking an activity's completion."""

    id: str
    name: str
    status: Optional[str] = None


class ActivityCompletionEligibilityResponse(ResponseModel):
    """Read-only result of the dependency completion-eligibility check:
    whether every dependency target of the activity is completed, plus the
    list of any that are not. ``eligible`` is True when there are no
    blockers (including the no-dependencies case)."""

    activity_id: str
    eligible: bool
    blocking_dependencies: List[CompletionBlocker] = Field(default_factory=list)


class ActivityAttachmentInput(BaseModel):
    """One inline attachment on a MEETING activity-create payload.

    The meeting (governance/mom) service forwards documents captured in
    the meeting form as base64 inside the JSON create body so the request
    stays JSON (not multipart). ``content`` is the raw base64 string with
    NO ``data:...;base64,`` prefix (the FE strips it). Honoured only when
    the parent milestone is the project's meeting milestone — otherwise
    rejected (see ``ActivityService.create``).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    filename: Annotated[str, Field(min_length=1, max_length=255)]
    content_type: Annotated[Optional[str], Field(default=None, max_length=255)]
    content: str


class ActivityCreateRequest(BaseModel):
    """POST /project/milestones/{milestone_id}/activities/create body — JSON arm.

    ``milestone_id`` comes from the URL path, not the body. On the
    multipart arm the same fields arrive as form values, plus an optional
    ``body`` (inline comment text) and ``files`` (uploads). Array /
    object fields are JSON-encoded inside multipart.
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    activity_started: Optional[bool] = False
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    position: Optional[int] = None
    owner_division: Annotated[Optional[str], Field(default=None, max_length=32)]
    # Monolith wire keeps the SINGULAR alias ``concernedDivision`` for FE
    # back-compat — only the datatype changed (string → list). Python
    # attribute stays plural to match the JSON DB column.
    concerned_divisions: Optional[List[str]] = Field(
        default=None, alias="concernedDivision",
    )
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    depends_on: List[str] = Field(default_factory=list)
    # Planned-resource allocations for a resource-based activity (replace-set).
    resources: List[ActivityPlannedResourceItem] = Field(default_factory=list)
    # 'planned' | 'additional' — only for activities under a resource-based
    # milestone (rejected otherwise). Defaults to 'planned' for resource-based
    # activities when omitted (see ActivityService.create).
    resource_classification: Annotated[
        Optional[str], Field(default=None, max_length=12)
    ]
    # Finance — optional on the wire. Pre-publish creates IGNORE
    # category/ccnValue and force 'original'/0; post-publish creates
    # default category to 'asg' when omitted, and require ccnValue > 0
    # when category='ccn'. See activity_service.create for full lifecycle.
    category: Annotated[Optional[str], Field(default=None, max_length=16)]
    ccn_value: Annotated[Optional[Decimal], Field(default=None, ge=0)]
    # Inline attachments for MEETING activities only — the meeting service
    # forwards meeting documents base64-encoded inside this JSON create
    # body. Honoured only when the parent milestone is the project's
    # meeting milestone; rejected with a 422 otherwise (see
    # ActivityService.create). The project-management FE never sends this
    # field (it attaches after create via the multipart /comments path),
    # so existing create flows are unaffected.
    attachments: Optional[List[ActivityAttachmentInput]] = Field(default=None)

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().upper()
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if v not in _ACTIVITY_STATUS_CHOICES:
            raise ValueError(
                f"Activity status must be one of: "
                f"{', '.join(_ACTIVITY_STATUS_CHOICES)}."
            )
        return v

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().lower()
        return v

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v):
        if v is None:
            return v
        if v not in _M_A_CATEGORY_CHOICES:
            raise ValueError(
                f"Category must be one of: "
                f"{', '.join(_M_A_CATEGORY_CHOICES)}."
            )
        return v

    @field_validator("resource_classification", mode="before")
    @classmethod
    def _normalize_resource_classification(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
        return v

    @field_validator("resource_classification")
    @classmethod
    def _validate_resource_classification(cls, v):
        if v is not None and v not in _RESOURCE_CLASSIFICATION_CHOICES:
            raise ValueError(
                "resourceClassification must be one of: "
                f"{', '.join(_RESOURCE_CLASSIFICATION_CHOICES)}."
            )
        return v

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError("End date cannot be before the start date.")
        return v


class ActivityUpdateRequest(BaseModel):
    """PATCH /project/activities/{id} body — partial update.

    Legacy ``resource`` sidecar isn't accepted on the wire (DB column
    kept for read-side compat with legacy rows). ``depends_on`` replaces
    the existing dependency list when supplied.
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    activity_started: Optional[bool] = None
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    owner_division: Annotated[Optional[str], Field(default=None, max_length=32)]
    # Monolith parity: singular wire alias on PATCH too.
    concerned_divisions: Optional[List[str]] = Field(
        default=None, alias="concernedDivision",
    )
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    position: Optional[int] = None
    depends_on: Optional[List[str]] = None
    # Planned-resource allocations — None = leave unchanged; [] = clear.
    resources: Optional[List[ActivityPlannedResourceItem]] = None
    # 'planned' | 'additional' — only for resource-based-milestone activities.
    resource_classification: Annotated[
        Optional[str], Field(default=None, max_length=12)
    ]
    # Finance — optional on PATCH. Service layer locks category once set
    # (409 if changed) and accepts ccn_value updates only when the
    # existing row's category is 'ccn'.
    category: Annotated[Optional[str], Field(default=None, max_length=16)]
    ccn_value: Annotated[Optional[Decimal], Field(default=None, ge=0)]

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().upper()
        return v

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if v not in _ACTIVITY_STATUS_CHOICES:
            raise ValueError(
                f"Activity status must be one of: "
                f"{', '.join(_ACTIVITY_STATUS_CHOICES)}."
            )
        return v

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().lower()
        return v

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v):
        if v is None:
            return v
        if v not in _M_A_CATEGORY_CHOICES:
            raise ValueError(
                f"Category must be one of: "
                f"{', '.join(_M_A_CATEGORY_CHOICES)}."
            )
        return v

    @field_validator("resource_classification", mode="before")
    @classmethod
    def _normalize_resource_classification(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
        return v

    @field_validator("resource_classification")
    @classmethod
    def _validate_resource_classification(cls, v):
        if v is not None and v not in _RESOURCE_CLASSIFICATION_CHOICES:
            raise ValueError(
                "resourceClassification must be one of: "
                f"{', '.join(_RESOURCE_CLASSIFICATION_CHOICES)}."
            )
        return v

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError("End date cannot be before the start date.")
        return v
