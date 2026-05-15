"""Pydantic v2 schemas for the activity_types catalog (doc 37)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class ActivityTypeCreateRequest(BaseModel):
    """Body of POST /masters/activity-types/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")]
    label: Annotated[str, Field(min_length=1, max_length=255)]
    active: bool = Field(default=True)


class ActivityTypeUpdateRequest(BaseModel):
    """Body of PATCH /masters/activity-types/{code}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    active: Annotated[Optional[bool], Field(default=None)]


class ActivityTypeResponse(BaseModel):
    """Returned by GET /masters/activity-types/list and /details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    label: str
    is_builtin: bool
    active: bool
    created_at: datetime
    updated_at: datetime
