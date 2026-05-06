"""Activity API schemas.

Doc 38: ``type`` (standard / resource / transactional) and the resource
block (``resourceMode`` / ``resourceCount`` / ``resource``) are
deprecated and were dropped from both create and update wire bodies.
DB columns kept for legacy reads. Single create endpoint:
``POST /milestones/{id}/activities/create``.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ....shared.datetime import IstCalendarDate
from ....domain.activities.activity import ACTIVITY_STATUS_CHOICES


class ActivityCreateRequest(BaseModel):
    """POST /milestones/{milestone_id}/activities/create.

    Doc 38 minimal shape: name + description + dates + ownership
    fields. ``status`` / ``dependsOn`` / ``actualStartDate`` /
    ``actualEndDate`` are NOT accepted here — they belong on PATCH.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization.
    start_date: IstCalendarDate = Field(..., alias="startDate")
    end_date: IstCalendarDate = Field(..., alias="endDate")
    position: Optional[int] = Field(None, ge=0)

    # Doc 38: optional ownership / partner / consulted-division fields.
    # Both division fields reference the divisions catalog (codes
    # tmd1 / tmd2 / others). vendorId references vendors.id (typically
    # one of the project's vendors, but not enforced server-side).
    owner_division: Optional[str] = Field(None, alias="ownerDivision")
    concerned_division: Optional[str] = Field(None, alias="concernedDivision")
    vendor_id: Optional[str] = Field(None, alias="vendorId")

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        s = info.data.get("start_date")
        if s is not None and v < s:
            raise ValueError("End date cannot be before the start date.")
        return v


class ActivityUpdateRequest(BaseModel):
    """PATCH /activities/{id}. Partial update — doc 38 wire surface only.

    Legacy ``type`` / ``resourceMode`` / ``resourceCount`` / ``resource``
    were dropped from the wire (DB columns kept for read-side compat).

    ``dependsOn`` semantics: None = no change, [] = clear, [...] = replace.
    """
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization.
    start_date: Optional[IstCalendarDate] = Field(None, alias="startDate")
    end_date: Optional[IstCalendarDate] = Field(None, alias="endDate")
    actual_start_date: Optional[IstCalendarDate] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[IstCalendarDate] = Field(None, alias="actualEndDate")
    position: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    depends_on: Optional[List[str]] = Field(None, alias="dependsOn")

    # Doc 38 additions.
    owner_division: Optional[str] = Field(None, alias="ownerDivision")
    concerned_division: Optional[str] = Field(None, alias="concernedDivision")
    vendor_id: Optional[str] = Field(None, alias="vendorId")

    @field_validator("status", mode="before")
    @classmethod
    def _validate_status(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip().lower()
        if v not in ACTIVITY_STATUS_CHOICES:
            raise ValueError(
                f"Activity status must be one of: {', '.join(ACTIVITY_STATUS_CHOICES)}."
            )
        return v


class ActivityListQuery(BaseModel):
    offset: int = Field(1, ge=1)
    pageSize: int = Field(20, ge=1, le=100)
    includeDeleted: bool = Field(False)
