"""Pydantic v2 schemas for the activity_statuses catalog (doc 37)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._base import ResponseModel


class ActivityStatusCreateRequest(BaseModel):
    """Body of POST /masters/activity-statuses/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")]
    label: Annotated[str, Field(min_length=1, max_length=255)]
    is_terminal: bool = Field(default=False, description="True = activities with this status are done")
    active: bool = Field(default=True)


class ActivityStatusUpdateRequest(BaseModel):
    """Body of PATCH /masters/activity-statuses/{code}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    is_terminal: Annotated[Optional[bool], Field(default=None)]
    active: Annotated[Optional[bool], Field(default=None)]


class ActivityStatusResponse(ResponseModel):
    """Returned by GET /masters/activity-statuses/list and /details."""

    id: int
    code: str
    label: str
    is_builtin: bool
    is_terminal: bool
    active: bool
    created_at: datetime
    updated_at: datetime
