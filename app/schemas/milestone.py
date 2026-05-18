"""Milestone schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.schemas._base import ResponseModel
from app.schemas.comment import CommentResponse


# Shared config — accept both camelCase aliases AND snake_case names on
# the wire (matches monolith's ``populate_by_name=True`` convention).
_REQUEST_CONFIG = ConfigDict(
    alias_generator=to_camel,
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


# Monolith parity: schema-level status validation uses this 2-value
# hardcoded set on create + update — milestone status only has
# ``not_completed`` / ``completed`` (no other transitions exposed on the
# wire).
_MILESTONE_STATUS_CHOICES = ("not_completed", "completed")


class MilestoneResponse(ResponseModel):
    """Field order matches monolith ``format_milestone_response`` byte-for-byte:
    id, displayCode, projectId, name, description, startDate, endDate,
    actualStartDate, actualEndDate, position, status, priority, dependsOn,
    dependsOnDisplay, vendors, createdAt, updatedAt, createdBy, updatedBy,
    deletedAt.

    Note: ``deletedBy`` is NOT on the wire (monolith parity — only
    ``deletedAt`` is exposed for milestone).
    """
    id: str
    # Sequential per-project label, e.g., "M1" / "M2" / "M3" — computed
    # in the controller from ``position``.
    display_code: Optional[str] = None
    project_id: str
    name: str
    description: Optional[str] = None
    start_date: datetime
    end_date: datetime
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    position: int
    status: str
    priority: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    # ``dependsOnDisplay`` mirrors ``depends_on`` but with each UUID
    # resolved to its target milestone's displayCode (e.g., ["M1"]).
    # Controller populates this.
    depends_on_display: List[str] = Field(default_factory=list)
    # Monolith milestone responses always carry an empty vendors list on
    # the wire (vendor association is not stored on the milestone row
    # itself in monolith). Controller leaves this empty.
    vendors: List[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    # Inline first comment that the MULTIPART arm of /create creates when
    # ``body`` and/or ``files`` are supplied alongside the entity fields.
    # ``None`` (and the wrap layer drops the key) on the JSON arm and on
    # all subsequent reads.
    comment: Optional[CommentResponse] = None


class MilestoneCreateRequest(BaseModel):
    """POST /project/projects/{uuid}/milestones/create body — JSON arm.

    On the multipart arm the same fields arrive as form values, plus an
    optional ``body`` (inline comment text) and ``files`` (uploads). The
    array fields (``depends_on``, ``vendor_ids``) are JSON-encoded inside
    multipart.
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
    depends_on: List[str] = Field(default_factory=list)
    vendor_ids: List[str] = Field(default_factory=list)

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
        if v not in _MILESTONE_STATUS_CHOICES:
            raise ValueError(
                f"Milestone status must be one of: "
                f"{', '.join(_MILESTONE_STATUS_CHOICES)}."
            )
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


class MilestoneUpdateRequest(BaseModel):
    """PATCH /project/milestones/{id} body — partial update. ``depends_on``
    and ``vendor_ids`` replace the existing lists when supplied."""

    model_config = _REQUEST_CONFIG

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=5000)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    position: Optional[int] = None
    depends_on: Optional[List[str]] = None
    vendor_ids: Optional[List[str]] = None

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
        if v not in _MILESTONE_STATUS_CHOICES:
            raise ValueError(
                f"Milestone status must be one of: "
                f"{', '.join(_MILESTONE_STATUS_CHOICES)}."
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
