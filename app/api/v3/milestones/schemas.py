"""Milestone API schemas (request/response)."""
from datetime import datetime
from typing import Any, List, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from ....domain.milestones.milestone import (
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_DEFAULT,
)


class MilestoneCreateRequest(BaseModel):
    """Request body for creating a milestone under a project."""
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    start_date: datetime = Field(..., alias="startDate")
    end_date: datetime = Field(..., alias="endDate")
    position: Optional[int] = Field(None, ge=0, description="Optional; auto-assigned if omitted")

    # Configurable status — values in MILESTONE_STATUS_CHOICES. Defaults to
    # 'not_completed' when omitted.
    status: str = Field(
        MILESTONE_STATUS_DEFAULT,
        description=f"One of: {', '.join(MILESTONE_STATUS_CHOICES)}",
    )
    # Reserved: a list of other milestone ids this one depends on. No
    # referential integrity is enforced yet; stored as-is.
    depends: Optional[List[Any]] = Field(None)
    # Optional subset of the project's vendors. Each id MUST also appear in
    # the project's vendor list (enforced by the service layer).
    #
    # The API field name is ``vendors`` (post-rename in doc 15). The legacy
    # ``vendorIds`` and ``vendor_ids`` names are also accepted as input so
    # callers built against the old contract keep working until they
    # migrate. Responses use ``vendors`` only.
    vendors: Optional[List[str]] = Field(
        None,
        validation_alias=AliasChoices("vendors", "vendorIds", "vendor_ids"),
        serialization_alias="vendors",
        description="List of vendor UUIDs to attach to this milestone.",
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
            return MILESTONE_STATUS_DEFAULT
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in MILESTONE_STATUS_CHOICES:
            raise ValueError(
                f"Milestone status must be one of: {', '.join(MILESTONE_STATUS_CHOICES)}."
            )
        return v


class MilestoneUpdateRequest(BaseModel):
    """Partial update. Unspecified fields are left unchanged."""
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    start_date: Optional[datetime] = Field(None, alias="startDate")
    end_date: Optional[datetime] = Field(None, alias="endDate")
    position: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    depends: Optional[List[Any]] = None
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
