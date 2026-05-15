"""Pydantic v2 schemas for the milestone_statuses catalog (doc 37).

Same shape as activity_status — kept separate per Way A so future divergence
(e.g. milestone-only fields) doesn't require renaming.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class MilestoneStatusCreateRequest(BaseModel):
    """Body of POST /masters/milestone-statuses/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")]
    label: Annotated[str, Field(min_length=1, max_length=255)]
    is_terminal: bool = Field(default=False, description="True = milestones with this status are done")
    active: bool = Field(default=True)


class MilestoneStatusUpdateRequest(BaseModel):
    """Body of PATCH /masters/milestone-statuses/{code}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    label: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    is_terminal: Annotated[Optional[bool], Field(default=None)]
    active: Annotated[Optional[bool], Field(default=None)]


class MilestoneStatusResponse(BaseModel):
    """Returned by GET /masters/milestone-statuses/list and /details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    label: str
    is_builtin: bool
    is_terminal: bool
    active: bool
    created_at: datetime
    updated_at: datetime
