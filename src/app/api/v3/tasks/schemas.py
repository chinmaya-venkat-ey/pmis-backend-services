"""Task API schemas.

Doc 38: ``type`` / ``resourceMode`` / ``resourceCount`` / ``resource``
were dropped from both create and update request bodies. DB columns
kept for legacy reads. CREATE now accepts only name / desc / dates.
UPDATE adds dates (actual + planned), position, dependsOn, status.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ....shared.datetime import IstCalendarDate


class TaskCreateRequest(BaseModel):
    """POST /activities/{activity_id}/tasks/create.

    Unified shape: same superset of fields as PATCH. Required fields
    stay required (name + dates); everything else is optional and falls
    back to a sensible default on omission. Comments / attachments
    remain on dedicated endpoints (only meaningful after the task has
    an id).
    """
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization (calendar-date semantics).
    start_date: IstCalendarDate = Field(..., alias="startDate")
    end_date: IstCalendarDate = Field(..., alias="endDate")
    actual_start_date: Optional[IstCalendarDate] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[IstCalendarDate] = Field(None, alias="actualEndDate")
    position: Optional[int] = Field(None, ge=0)
    status: Optional[str] = None
    depends_on: Optional[List[str]] = Field(None, alias="dependsOn")

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v, info):
        s = info.data.get("start_date")
        if s is not None and v < s:
            raise ValueError("End date cannot be before the start date.")
        return v


class TaskUpdateRequest(BaseModel):
    """PATCH /tasks/{id}. Partial update — doc 38 wire surface only.

    Legacy ``type`` / ``resourceMode`` / ``resourceCount`` / ``resource``
    were dropped from the wire (DB columns kept for read-side compat).
    """
    model_config = ConfigDict(populate_by_name=True)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    # Doc 29: IstCalendarDate normalization (calendar-date semantics).
    start_date: Optional[IstCalendarDate] = Field(None, alias="startDate")
    end_date: Optional[IstCalendarDate] = Field(None, alias="endDate")
    actual_start_date: Optional[IstCalendarDate] = Field(None, alias="actualStartDate")
    actual_end_date: Optional[IstCalendarDate] = Field(None, alias="actualEndDate")
    position: Optional[int] = Field(None, ge=0)
    depends_on: Optional[List[str]] = Field(None, alias="dependsOn")
    # Doc 38: lifecycle status, accepted on PATCH only.
    status: Optional[str] = None


class TaskListQuery(BaseModel):
    offset: int = Field(1, ge=1)
    pageSize: int = Field(20, ge=1, le=100)
    includeDeleted: bool = Field(False)
