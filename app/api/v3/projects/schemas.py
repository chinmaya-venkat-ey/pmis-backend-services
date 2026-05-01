"""
Project API schemas (request/response models).
"""
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator, ConfigDict

from .services.transitions import (
    CATEGORY_OTHERS,
    PROJECT_STATUS_CHOICES,
    PROJECT_CATEGORY_CHOICES,
)


class ProjectCreateRequest(BaseModel):
    """Request schema for creating a project.

    The server generates ``id`` (UUID) and ``projectCode`` on insert; neither
    is accepted in the request body.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    active: bool = Field(True)
    public: bool = Field(False, alias="isPublic")
    statusExplanation: Optional[str] = Field(None, max_length=5000, alias="status_explanation")
    parentId: Optional[str] = Field(None, alias="parent_id", description="Parent project UUID")
    status: str = Field(
        "new",
        description=f"Project status. One of: {', '.join(PROJECT_STATUS_CHOICES)}",
    )
    owner: Optional[str] = Field(
        None, min_length=1, max_length=255,
        description=(
            "Project owner — division code: 'tmd1' / 'tmd2' / 'others'. "
            "Required at the service layer on create + upsert. When set "
            "to 'others', a non-empty `ownerOther` follow-up label is "
            "required (max 255 chars)."
        ),
    )
    ownerOther: Optional[str] = Field(
        None,
        alias="owner_other",
        max_length=255,
        description=(
            "Required (non-empty) when owner == 'others'. Must be omitted / "
            "null for any other owner value."
        ),
    )
    category: Optional[str] = Field(
        None,
        description=f"Category. One of: {', '.join(PROJECT_CATEGORY_CHOICES)}",
    )
    categoryOther: Optional[str] = Field(
        None,
        alias="category_other",
        max_length=255,
        description=(
            f"Required (non-empty) when category == '{CATEGORY_OTHERS}'. "
            "Must be omitted / null for any other category."
        ),
    )
    categoryOtherReason: Optional[str] = Field(
        None,
        alias="category_other_reason",
        max_length=1000,
        description=(
            f"Required when category == '{CATEGORY_OTHERS}'. Free-text "
            "explanation of why 'others' was picked instead of MSAP/MSIP/"
            "BSP. Captured for governance / category-curation review."
        ),
    )
    vendorIds: Optional[List[str]] = Field(
        None,
        alias="vendor_ids",
        description="Optional list of vendor UUIDs to associate with this project.",
    )
    start_date: Optional[datetime] = Field(None, alias="startDate")
    end_date: Optional[datetime] = Field(None, alias="endDate")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in PROJECT_STATUS_CHOICES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {', '.join(PROJECT_STATUS_CHOICES)}"
            )
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v):
        if v is not None and v not in PROJECT_CATEGORY_CHOICES:
            raise ValueError(
                f"Invalid category '{v}'. Allowed: {', '.join(PROJECT_CATEGORY_CHOICES)}"
            )
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_dates_in_future(cls, v):
        if v is not None:
            now = datetime.now(timezone.utc)
            check_v = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
            if check_v <= now:
                raise ValueError("Date must be in the future")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_date_after_start_date(cls, v, info):
        if v is not None and "start_date" in info.data and info.data["start_date"] is not None:
            # Inclusive: end_date == start_date is allowed (one-day projects /
            # milestones / activities). Only reject when end is strictly before.
            if v < info.data["start_date"]:
                raise ValueError("end_date cannot be before start_date")
        return v


class ProjectUpdateRequest(BaseModel):
    """Request schema for updating a project (PATCH).

    The server filters supplied fields through the editable-field whitelist
    for the project's current state; fields outside the whitelist produce a
    422 invalid_field error. ``actualEndDate`` is accepted here because it is
    a version-only editable field.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    active: Optional[bool] = None
    public: Optional[bool] = Field(None, alias="isPublic")
    statusExplanation: Optional[str] = Field(None, max_length=5000, alias="status_explanation")
    parentId: Optional[str] = Field(None, alias="parent_id", description="Parent project UUID")
    status: Optional[str] = Field(None)
    owner: Optional[str] = Field(None, min_length=1, max_length=255)
    ownerOther: Optional[str] = Field(None, alias="owner_other", max_length=255)
    category: Optional[str] = Field(None)
    categoryOther: Optional[str] = Field(None, alias="category_other", max_length=255)
    categoryOtherReason: Optional[str] = Field(
        None, alias="category_other_reason", max_length=1000,
    )
    vendorIds: Optional[List[str]] = Field(
        None,
        alias="vendor_ids",
        description=(
            "Replace the full vendor list for this project. Omit to leave the "
            "existing list unchanged; send `[]` to clear."
        ),
    )
    start_date: Optional[datetime] = Field(None, alias="startDate")
    end_date: Optional[datetime] = Field(None, alias="endDate")
    actual_start_date: Optional[datetime] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[datetime] = Field(None, alias="actualEndDate")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in PROJECT_STATUS_CHOICES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {', '.join(PROJECT_STATUS_CHOICES)}"
            )
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v):
        if v is not None and v not in PROJECT_CATEGORY_CHOICES:
            raise ValueError(
                f"Invalid category '{v}'. Allowed: {', '.join(PROJECT_CATEGORY_CHOICES)}"
            )
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_dates_in_future(cls, v):
        if v is not None:
            now = datetime.now(timezone.utc)
            check_v = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
            if check_v <= now:
                raise ValueError("Date must be in the future")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_date_after_start_date(cls, v, info):
        if v is not None and "start_date" in info.data and info.data["start_date"] is not None:
            # Inclusive: end_date == start_date is allowed.
            if v < info.data["start_date"]:
                raise ValueError("end_date cannot be before start_date")
        return v


class ProjectListQuery(BaseModel):
    """Query parameters for listing projects."""

    offset: int = Field(1, ge=1, description="Page number (1-indexed)")
    pageSize: int = Field(20, ge=1, le=100)
    active: Optional[bool] = None
    public: Optional[bool] = None
    # When True, the response includes soft-deleted rows (the "All projects"
    # admin view). The default GET /projects endpoint pins this False; the
    # GET /projects/all endpoint pins it True.
    includeDeleted: bool = Field(False)


class ProjectCloseRequest(BaseModel):
    """Optional body for POST /projects/{id}/close."""
    model_config = ConfigDict(populate_by_name=True)

    reason: Optional[str] = Field(None, max_length=5000)


class ProjectUpsertRequest(BaseModel):
    """Body for PUT /projects/{project_uuid} (idempotent create-or-update).

    The project's ``id`` comes from the URL path (a UUID string). The server
    auto-generates ``projectCode`` on the INSERT branch and preserves it on
    the UPDATE branch. Neither ``id`` nor ``projectCode`` is accepted in the
    body.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    active: bool = Field(True)
    public: bool = Field(False, alias="isPublic")
    statusExplanation: Optional[str] = Field(None, max_length=5000, alias="status_explanation")
    parentId: Optional[str] = Field(None, alias="parent_id", description="Parent project UUID")
    status: str = Field("new")
    owner: Optional[str] = Field(None, min_length=1, max_length=255)
    ownerOther: Optional[str] = Field(None, alias="owner_other", max_length=255)
    category: Optional[str] = Field(None)
    categoryOther: Optional[str] = Field(None, alias="category_other", max_length=255)
    categoryOtherReason: Optional[str] = Field(
        None, alias="category_other_reason", max_length=1000,
    )
    vendorIds: Optional[List[str]] = Field(None, alias="vendor_ids")
    start_date: Optional[datetime] = Field(None, alias="startDate")
    end_date: Optional[datetime] = Field(None, alias="endDate")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v not in PROJECT_STATUS_CHOICES:
            raise ValueError(
                f"Invalid status '{v}'. Allowed: {', '.join(PROJECT_STATUS_CHOICES)}"
            )
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v):
        if v is not None and v not in PROJECT_CATEGORY_CHOICES:
            raise ValueError(
                f"Invalid category '{v}'. Allowed: {', '.join(PROJECT_CATEGORY_CHOICES)}"
            )
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_dates_in_future(cls, v):
        if v is not None:
            now = datetime.now(timezone.utc)
            check_v = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
            if check_v <= now:
                raise ValueError("Date must be in the future")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_date_after_start_date(cls, v, info):
        if v is not None and "start_date" in info.data and info.data["start_date"] is not None:
            # Inclusive: end_date == start_date is allowed.
            if v < info.data["start_date"]:
                raise ValueError("end_date cannot be before start_date")
        return v
