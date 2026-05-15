"""Permission schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    description: Optional[str] = None
    is_builtin: bool
    created_at: datetime
    updated_at: datetime


class PermissionCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    code: Annotated[str, Field(min_length=1, max_length=128,
                                pattern=r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$",
                                description="Domain:action format, e.g. 'users:create'")]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]


class PermissionUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: Annotated[Optional[str], Field(default=None, min_length=1, max_length=255)]
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]


class EffectivePermissionsResponse(BaseModel):
    """Returned by GET /user/users/me/permissions/list and /user/users/{id}/permissions/list."""

    model_config = ConfigDict(from_attributes=True)
    user_id: str
    permissions: List[str] = Field(default_factory=list)
    is_admin: bool = False


class PermissionsByModuleResponse(BaseModel):
    """Returned by GET /user/permissions/by-module/list.

    Permissions grouped by their `domain` prefix — useful for admin UIs that
    render a tree of "Users / Projects / Masters / ..." with codes nested.
    """

    model_config = ConfigDict(from_attributes=True)
    modules: Dict[str, List[PermissionResponse]] = Field(default_factory=dict)
