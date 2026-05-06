"""Milestone API schemas (request/response)."""
from datetime import datetime
from typing import List, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from ....domain.milestones.milestone import (
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_DEFAULT,
)
from ....shared.datetime import IstCalendarDate


class MilestoneCreateRequest(BaseModel):
    """Request body for creating a milestone under a project.

    Doc 38: trimmed to name + description + dates only. Status,
    dependsOn, vendors, and position are no longer accepted on create —
    set them via PATCH after the row exists.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalizes any submitted datetime to IST
    # midnight so milestone-vs-project comparisons don't trip on
    # encoding mismatches.
    start_date: IstCalendarDate = Field(..., alias="startDate")
    end_date: IstCalendarDate = Field(..., alias="endDate")

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        start = info.data.get("start_date")
        if start is not None and v < start:
            raise ValueError("End date cannot be before the start date.")
        return v


class MilestoneUpdateRequest(BaseModel):
    """Partial update. Unspecified fields are left unchanged."""
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization (see MilestoneCreateRequest).
    start_date: Optional[IstCalendarDate] = Field(None, alias="startDate")
    end_date: Optional[IstCalendarDate] = Field(None, alias="endDate")
    position: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    depends_on: Optional[List[str]] = Field(
        None,
        alias="dependsOn",
    )
    # Same renaming + back-compat aliases as the create schema.
    vendors: Optional[List[str]] = Field(
        None,
        validation_alias=AliasChoices("vendors", "vendorIds", "vendor_ids"),
        serialization_alias="vendors",
    )

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


class MilestoneListQuery(BaseModel):
    offset: int = Field(1, ge=1)
    pageSize: int = Field(20, ge=1, le=100)
    includeDeleted: bool = Field(False)
