"""Task + task-resource schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, List, Optional

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


class TaskResourceSchema(ResponseModel):
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


class TaskResponse(ResponseModel):
    """Field order matches monolith ``format_task_response`` byte-for-byte:
    id, displayCode, projectId, activityId, name, description, type,
    startDate, endDate, actualStartDate, actualEndDate, position,
    resourceMode, resourceCount, status, priority, assignedTo,
    assignedToName, dependsOn, dependsOnDisplay, createdAt, updatedAt,
    createdBy, updatedBy, deletedAt, resource.

    Note: monolith does NOT validate task status against any catalog
    (arbitrary strings are persisted as-is on the wire — e.g.
    ``"in_review"`` is accepted at 201 even though it's not in the
    masters list). This schema therefore omits a status field_validator.
    """
    id: str
    # Sequential per-activity label, e.g., "T1.1.1" — computed in the
    # controller from milestone.position + activity.position + position.
    display_code: Optional[str] = None
    project_id: str
    activity_id: str
    name: str
    description: Optional[str] = None
    type: Optional[str] = None
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    position: int
    resource_mode: Optional[str] = None
    resource_count: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    # Resolved display name for ``assigned_to`` user (``"<first> <last>"``)
    # — controller populates from users.users mirror.
    assigned_to_name: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    # UUIDs resolved to "T<m_pos>.<a_pos>.<t_pos>" labels.
    depends_on_display: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    resource: Optional[TaskResourceSchema] = None
    # Inline first comment populated only on the multipart /create arm
    # when body/files are supplied. Dropped when ``None``.
    comment: Optional[CommentResponse] = None


class TaskCreateRequest(BaseModel):
    """POST /project/activities/{activity_id}/tasks/create body — JSON arm.

    ``activity_id`` comes from the URL path, not the body. On the
    multipart arm the same fields arrive as form values, plus an optional
    ``body`` (inline comment text) and ``files`` (uploads). Array fields
    are JSON-encoded inside multipart.

    Note: monolith does NOT validate ``status`` against any catalog on
    create — arbitrary strings are stored verbatim. Schema therefore has
    NO status field_validator here.
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    # Monolith parity: priority is REQUIRED on create (Doc-41).
    priority: Annotated[str, Field(min_length=1, max_length=16)]
    position: Optional[int] = None
    assigned_to: Annotated[Optional[str], Field(default=None, max_length=36)]
    depends_on: List[str] = Field(default_factory=list)

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        if isinstance(v, str):
            v = v.strip().upper()
        return v

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        # Monolith parity: ``"End date cannot be before the start date."``
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError("End date cannot be before the start date.")
        return v


class TaskUpdateRequest(BaseModel):
    """PATCH /project/tasks/{id} body — partial update. ``depends_on``
    replaces the existing dependency list when supplied. Legacy
    ``resource`` sidecar isn't accepted on the wire."""

    model_config = _REQUEST_CONFIG

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    assigned_to: Annotated[Optional[str], Field(default=None, max_length=36)]
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

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError("End date cannot be before the start date.")
        return v
