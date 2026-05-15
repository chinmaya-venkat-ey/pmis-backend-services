"""Pydantic v2 schemas for the project_status_transitions catalog.

`from_status=None` represents the initial-status seed (status the system
accepts on a fresh create). For non-initial edges, both columns are required.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectStatusTransitionCreateRequest(BaseModel):
    """Body of POST /masters/project-status-transitions/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    from_status: Annotated[
        Optional[str],
        Field(default=None, max_length=50,
              description="NULL = initial-status seed (status accepted on fresh create)"),
    ]
    to_status: Annotated[str, Field(min_length=1, max_length=50)]
    requires_admin: bool = Field(default=False, description="If true, only admin can take this edge")
    active: bool = Field(default=True)
    description: Annotated[Optional[str], Field(default=None, max_length=500)]


class ProjectStatusTransitionUpdateRequest(BaseModel):
    """Body of PATCH /masters/project-status-transitions/{row_id}/update — partial.

    `from_status` and `to_status` are immutable — to change an edge, delete + re-create.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    requires_admin: Annotated[Optional[bool], Field(default=None)]
    active: Annotated[Optional[bool], Field(default=None)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]


class ProjectStatusTransitionResponse(BaseModel):
    """Returned by GET /masters/project-status-transitions/list and /details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: Optional[str] = None
    to_status: str
    requires_admin: bool
    active: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
