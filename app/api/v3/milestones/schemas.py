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
    """Request body for creating a milestone under a project."""
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalizes any submitted datetime to IST
    # midnight of the IST-local calendar date — collapses cross-format
    # FE inputs (UTC Z, IST +05:30, naive, end-of-day variants) to a
    # single canonical instant so milestone-vs-project comparisons
    # don't trip on encoding mismatches.
    start_date: IstCalendarDate = Field(..., alias="startDate")
    end_date: IstCalendarDate = Field(..., alias="endDate")
    position: Optional[int] = Field(None, ge=0, description="Optional; auto-assigned if omitted")

    # Configurable status — values in MILESTONE_STATUS_CHOICES. Defaults to
    # 'not_completed' when omitted.
    status: str = Field(
        MILESTONE_STATUS_DEFAULT,
        description=f"One of: {', '.join(MILESTONE_STATUS_CHOICES)}",
    )
    # Other milestone ids in the SAME project this milestone depends on.
    # Same-project, no self-edge, acyclic — enforced in the service layer
    # against the milestone_dependencies edge table. Empty / null = no
    # dependencies.
    #
    # Accepts either UUIDs or display labels (e.g. "M2"). The service
    # resolves labels to UUIDs at write time. Wire field is `dependsOn`
    # (camelCase) — matches activity / task / subtask schemas exactly.
    depends_on: Optional[List[str]] = Field(
        None,
        alias="dependsOn",
    )
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
        description=(
            "Vendor identifiers to attach to this milestone. Each entry "
            "can be a UUID or a ``VN-...`` code (doc 25); the list may "
            "freely mix the two forms."
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
