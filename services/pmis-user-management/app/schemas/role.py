"""Role schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    builtin: bool
    created_at: datetime
    updated_at: datetime


class RoleCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]


class RoleUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]


class RolePermissionsResponse(BaseModel):
    """Returned by GET /user/roles/{id}/permissions/list — flat list of codes
    plus the role meta."""

    model_config = ConfigDict(from_attributes=True)
    role_id: int
    role_name: str
    permissions: List[str] = Field(default_factory=list)


class RolePermissionsReplaceRequest(BaseModel):
    """PUT /user/roles/{id}/permissions/replace — full-replace the set."""

    model_config = ConfigDict(extra="forbid")
    permissions: List[str] = Field(default_factory=list)
