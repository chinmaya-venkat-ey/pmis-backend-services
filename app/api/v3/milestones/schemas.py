"""Milestone API schemas (request/response)."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ....domain.milestones.milestone import (
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_DEFAULT,
)
from ....domain.priorities.priority import PRIORITY_CHOICES
from ....shared.datetime import IstCalendarDate


class MilestoneCreateRequest(BaseModel):
    """Request body for creating a milestone under a project.

    Unified shape (post-doc 39 follow-up): create accepts the same
    superset of fields as PATCH. Required fields stay required;
    everything else is optional and falls back to a sensible default
    on omission. ``status`` defaults to ``not_completed`` if omitted;
    ``dependsOn`` defaults to ``[]`` (no edges).
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalizes any submitted datetime to IST
    # midnight so milestone-vs-project comparisons don't trip on
    # encoding mismatches.
    start_date: IstCalendarDate = Field(..., alias="startDate")
    end_date: IstCalendarDate = Field(..., alias="endDate")
    # Tester report: actual dates added so the FE can render them on
    # the edit form, matching the activity / task / subtask shape.
    # Optional at create — usually populated later via PATCH when work
    # actually starts / finishes.
    actual_start_date: Optional[IstCalendarDate] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[IstCalendarDate] = Field(None, alias="actualEndDate")
    position: Optional[int] = Field(None, ge=0)
    # Optional on create; if omitted the service defaults to ``not_completed``.
    status: Optional[str] = None
    # Optional on create. List of milestone UUIDs or display labels (M1, M2, …).
    depends_on: Optional[List[str]] = Field(None, alias="dependsOn")
    # Doc 41 follow-up: priority code — REQUIRED on create. Independent
    # per-level — milestone priority is not derived from / constrained by
    # activity priority.
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
        start = info.data.get("start_date")
        if start is not None and v < start:
            raise ValueError("End date cannot be before the start date.")
        return v

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in MILESTONE_STATUS_CHOICES:
            raise ValueError(
                f"Milestone status must be one of: {', '.join(MILESTONE_STATUS_CHOICES)}."
            )
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
        return v


class MilestoneUpdateRequest(BaseModel):
    """Partial update. Unspecified fields are left unchanged.

    Doc 39: ``vendors`` was removed from the wire — vendor association
    moved off milestones onto activities (one vendor per activity).
    The DB table ``milestone_vendors`` and ``MilestoneVendorModel`` are
    kept on disk for backwards-compat with legacy rows; the API silently
    strips ``vendors`` if a caller still sends it.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization (see MilestoneCreateRequest).
    start_date: Optional[IstCalendarDate] = Field(None, alias="startDate")
    end_date: Optional[IstCalendarDate] = Field(None, alias="endDate")
    # Tester report: actual dates editable on PATCH. Optional —
    # None on PATCH means "no change" (consistent with other fields).
    actual_start_date: Optional[IstCalendarDate] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[IstCalendarDate] = Field(None, alias="actualEndDate")
    position: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    depends_on: Optional[List[str]] = Field(
        None,
        alias="dependsOn",
    )
    # Doc 41 follow-up: priority code — optional on PATCH (None = no change).
    priority: Optional[str] = Field(None, max_length=16)

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in MILESTONE_STATUS_CHOICES:
            raise ValueError(
                f"Milestone status must be one of: {', '.join(MILESTONE_STATUS_CHOICES)}."
            )
        return v

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().lower()
        return v


class MilestoneListQuery(BaseModel):
    offset: int = Field(1, ge=1)
    pageSize: int = Field(20, ge=1, le=100)
    includeDeleted: bool = Field(False)
