"""Milestone schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
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
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    depends_on: List[str] = Field(default_factory=list)
    vendor_ids: List[str] = Field(default_factory=list)


class MilestoneCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=10000)]
    start_date: datetime
    end_date: datetime
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    depends_on: List[str] = Field(default_factory=list)
    vendor_ids: List[str] = Field(default_factory=list)


class MilestoneUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=10000)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None
    status: Annotated[Optional[str], Field(default=None, max_length=32)]
    priority: Annotated[Optional[str], Field(default=None, max_length=16)]
    position: Optional[int] = None
