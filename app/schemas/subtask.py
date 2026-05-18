"""Subtask + subtask-resource schemas. Supports Doc-24 nesting (parent_subtask_id)."""
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


class SubtaskResourceSchema(ResponseModel):
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


class SubtaskResponse(ResponseModel):
    """Field order matches monolith ``format_subtask_response`` byte-for-byte:
    id, displayCode, projectId, taskId, parentSubtaskId, name, description,
    type, startDate, endDate, actualStartDate, actualEndDate, position,
    resourceMode, resourceCount, status, priority, assignedTo,
    assignedToName, dependsOn, dependsOnDisplay, createdAt, updatedAt,
    createdBy, updatedBy, deletedAt, resource.

    Note: monolith does NOT validate subtask status against any catalog
    (arbitrary strings persist as-is — same as task module).
    """
    id: str
    # Sequential per-parent label, e.g., "S1.1.1.1" — controller computes
    # from milestone.position + activity.position + task.position +
    # subtask.position. Nested subtasks share the same 4-segment format
    # using their own position within the immediate parent.
    display_code: Optional[str] = None
    project_id: str
    task_id: str
    parent_subtask_id: Optional[str] = None
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
    # Resolved display name for ``assigned_to`` user (``"<first> <last>"``).
    assigned_to_name: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    # UUIDs resolved to "S<m>.<a>.<t>.<s>" labels.
    depends_on_display: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    resource: Optional[SubtaskResourceSchema] = None
    # Hierarchical children populated ONLY by the list endpoint
    # (``GET /tasks/{id}/subtasks``). Single-resource reads leave this
    # ``None`` and the wrap layer drops the key entirely from the wire so
    # the single-GET shape matches the monolith's flat response.
    subtasks: Optional[List["SubtaskResponse"]] = None
    # Inline first comment populated only on the multipart /create arm.
    comment: Optional[CommentResponse] = None


SubtaskResponse.model_rebuild()


class SubtaskCreateRequest(BaseModel):
    """JSON arm body for both subtask create endpoints:

      * ``POST /project/tasks/{task_id}/subtasks`` (top-level)
      * ``POST /project/subtasks/{parent_subtask_id}/subtasks`` (nested,
        any depth)

    The parent reference (``task_id`` / ``parent_subtask_id``) comes from
    the URL path. On the multipart arm the same fields arrive as form
    values plus optional ``body`` (inline comment) and ``files``.

    Note: monolith does NOT validate ``status`` against any catalog on
    create — arbitrary strings are stored verbatim (same as task module).
    """

    model_config = _REQUEST_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    position: Optional[int] = None
    assigned_to: Annotated[Optional[str], Field(default=None, max_length=36)]
    depends_on: List[str] = Field(default_factory=list)

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
        # Monolith parity: ``"End date cannot be before the start date."``
        if v is not None and "start_date" in info.data:
            start = info.data["start_date"]
            if start is not None and v < start:
                raise ValueError("End date cannot be before the start date.")
        return v


class SubtaskUpdateRequest(BaseModel):
    """PATCH /project/subtasks/{id} body — partial update. ``depends_on``
    replaces the existing dependency list when supplied."""

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
