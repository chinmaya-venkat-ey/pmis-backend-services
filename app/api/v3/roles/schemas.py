"""
Role API schemas (request/response models).
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    """Request schema for creating a role."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    permissions: List[str] = Field(default_factory=list)
    # ``builtin`` is now ignored on create — the flag is reserved for the
    # startup-synced seed roles. Custom roles created via API are always
    # non-builtin. Field kept for API back-compat; value is forced to False
    # in the service.
    builtin: bool = Field(default=False)


class RoleUpdateRequest(BaseModel):
    """Request schema for updating a role."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    permissions: Optional[List[str]] = None


class RoleListQuery(BaseModel):
    """Query parameters for listing roles."""

    offset: int = Field(0, ge=0, description="Number of items to skip")
    pageSize: int = Field(20, ge=1, le=100, description="Number of items per page")


class RolePermissionsReplaceRequest(BaseModel):
    """Body for PUT /api/v3/roles/{id}/permissions."""

    permissions: List[str] = Field(default_factory=list)
