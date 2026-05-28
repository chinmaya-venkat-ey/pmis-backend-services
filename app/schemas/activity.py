"""Activity schemas + activity-resource sub-schema."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel
from app.schemas.comment import CommentResponse


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
    # Free-text label when owner_division is the catalog code 'others'.
    # Null/empty for any other code. Service layer enforces the pair rule.
    owner_division_other: Optional[str] = None
    # Singular Python name → singular wire (``concernedDivision``).
    # Value is a list (Doc-39 multi-division).
    concerned_division: Optional[List[Any]] = None
    # Free-text label when 'others' appears in concerned_divisions.
    # Single field per activity — one description suffices.
    concerned_division_other: Optional[str] = None
    vendor_id: Optional[str] = None
    priority: Optional[str] = None
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    position: int
    resource_mode: Optional[str] = None
    resource_count: Optional[int] = None
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
    # Inline first comment populated only on the multipart /create arm
    # when body/files are supplied. Dropped from the wire (by the camel
    # layer) when ``None``.
    comment: Optional[CommentResponse] = None


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
    # Required when owner_division == 'others'; must be empty otherwise.
    # Validated service-side. Wire alias is camelCase via _REQUEST_CONFIG.
    owner_division_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    # Monolith wire keeps the SINGULAR alias ``concernedDivision`` for FE
    # back-compat — only the datatype changed (string → list). Python
    # attribute stays plural to match the JSON DB column.
    concerned_divisions: Optional[List[str]] = Field(
        default=None, alias="concernedDivision",
    )
    # Required when 'others' appears in concerned_divisions; empty otherwise.
    concerned_division_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    depends_on: List[str] = Field(default_factory=list)

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
    owner_division_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    # Monolith parity: singular wire alias on PATCH too.
    concerned_divisions: Optional[List[str]] = Field(
        default=None, alias="concernedDivision",
    )
    concerned_division_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    position: Optional[int] = None
    depends_on: Optional[List[str]] = None

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

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError("End date cannot be before the start date.")
        return v
