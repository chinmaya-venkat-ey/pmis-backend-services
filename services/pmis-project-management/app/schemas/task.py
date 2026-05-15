"""Task + task-resource schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskResourceSchema(BaseModel):
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


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
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
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    depends_on: List[str] = Field(default_factory=list)
    resource: Optional[TaskResourceSchema] = None


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    activity_id: Annotated[str, Field(max_length=36)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=10000)]
    start_date: datetime
    end_date: datetime
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    assigned_to: Annotated[Optional[str], Field(default=None, max_length=36)]
    resource: Optional[TaskResourceSchema] = None
    depends_on: List[str] = Field(default_factory=list)


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=10000)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    assigned_to: Annotated[Optional[str], Field(default=None, max_length=36)]
    position: Optional[int] = None
    resource: Optional[TaskResourceSchema] = None
