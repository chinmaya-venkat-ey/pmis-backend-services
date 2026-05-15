"""Project schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_code: str
    name: str
    description: Optional[str] = None
    active: bool
    public: bool
    status_explanation: Optional[str] = None
    parent_id: Optional[str] = None

    status: str
    owner: Optional[str] = None
    owner_other: Optional[str] = None
    category: Optional[str] = None
    category_other: Optional[str] = None
    category_other_reason: Optional[str] = None

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None

    # Convenience embed — populated by the controller, not by the ORM.
    vendor_ids: List[str] = Field(default_factory=list)


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=10000)]
    public: bool = False
    parent_id: Annotated[Optional[str], Field(default=None, max_length=36)]

    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    owner_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category: Annotated[Optional[str], Field(default=None, max_length=50)]
    category_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    category_other_reason: Annotated[Optional[str], Field(default=None, max_length=1000)]

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    vendor_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _category_other_requires_reason(self):
        if self.category == "others" and not self.category_other_reason:
            raise ValueError("category_other_reason is required when category == 'others'")
        return self


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=10000)]
    public: Optional[bool] = None
    status_explanation: Annotated[Optional[str], Field(default=None, max_length=10000)]
    owner: Annotated[Optional[str], Field(default=None, max_length=255)]
    owner_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actual_start_date: Optional[datetime] = None
    actual_end_date: Optional[datetime] = None


class ProjectStatusTransitionRequest(BaseModel):
    """POST /project/projects/{uuid}/status/transition body."""

    model_config = ConfigDict(extra="forbid")
    to_status: Annotated[str, Field(min_length=1, max_length=50)]
    note: Annotated[Optional[str], Field(default=None, max_length=1000)]
