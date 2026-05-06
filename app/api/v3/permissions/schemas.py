"""Permission catalog API schemas."""
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


_VALID_CODE = r"^[a-z0-9_]+:[a-z0-9_]+$"


class PermissionCreateRequest(BaseModel):
    """Body for POST /api/v3/permissions."""
    model_config = ConfigDict(populate_by_name=True)

    code: str = Field(..., min_length=3, max_length=128, pattern=_VALID_CODE,
                      description="lowercase domain:action, e.g. 'projects:create'")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)


class PermissionUpdateRequest(BaseModel):
    """Body for PATCH /api/v3/permissions/{code}. Code is immutable."""
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)


class RolePermissionsReplaceRequest(BaseModel):
    """Body for PUT /api/v3/roles/{id}/permissions."""
    model_config = ConfigDict(populate_by_name=True)

    permissions: List[str] = Field(default_factory=list)
