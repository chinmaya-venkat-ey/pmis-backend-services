"""Role API schemas (request/response models)."""
from typing import List, Optional

from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    """Request schema for creating a role."""

    name: str = Field(..., min_length=1, max_length=255)
    permissions: List[str] = Field(default_factory=list)
    builtin: bool = Field(default=False)


class RoleUpdateRequest(BaseModel):
    """Request schema for updating a role."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    permissions: Optional[List[str]] = None


class RoleListQuery(BaseModel):
    """Query parameters for listing roles."""

    offset: int = Field(0, ge=0, description="Number of items to skip")
    pageSize: int = Field(20, ge=1, le=100, description="Number of items per page")
