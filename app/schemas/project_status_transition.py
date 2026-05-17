"""Pydantic v2 schemas for the project_status_transitions catalog.

`from_status=None` represents the initial-status seed (status the system
accepts on a fresh create). For non-initial edges, both columns are required.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._base import ResponseModel


class ProjectStatusTransitionCreateRequest(BaseModel):
    """Body of POST /masters/project-status-transitions/create.

    Round-7: gates by PERMISSION CODE instead of a boolean role flag. Callers
    set ``permission_code`` to the code the user must hold to take this edge
    (e.g. ``projects:publish`` / ``:close`` / ``:reopen`` / ``:draft``).
    NULL means the edge needs no special permission.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    from_status: Annotated[
        Optional[str],
        Field(default=None, max_length=50,
              description="NULL = initial-status seed (status accepted on fresh create)"),
    ]
    to_status: Annotated[str, Field(min_length=1, max_length=50)]
    permission_code: Annotated[
        Optional[str],
        Field(default=None, max_length=128,
              description="NULL = no special permission. Otherwise the code the caller must hold."),
    ]
    active: bool = Field(default=True)
    description: Annotated[Optional[str], Field(default=None, max_length=500)]


class ProjectStatusTransitionUpdateRequest(BaseModel):
    """Body of PATCH /masters/project-status-transitions/{row_id}/update — partial.

    `from_status` and `to_status` are immutable — to change an edge, delete + re-create.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    permission_code: Annotated[Optional[str], Field(default=None, max_length=128)]
    active: Annotated[Optional[bool], Field(default=None)]
    description: Annotated[Optional[str], Field(default=None, max_length=500)]


class ProjectStatusTransitionResponse(ResponseModel):
    """Returned by GET /masters/project-status-transitions/list and /details."""

    id: int
    from_status: Optional[str] = None
    to_status: str
    permission_code: Optional[str] = None
    active: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
