"""Role-grants matrix — which roles a caller can grant when they hold ROLE_X.

Returned by GET /user/role-grants/{role_name}/matrix. The matrix is static
in this iteration (lives in app/services/role_grants_service.py) and
encodes Doc-42b caller-vs-target rules.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class GrantableRole(BaseModel):
    name: str
    scope: str = Field(description="'global' | 'org' | 'project'")
    notes: str = ""


class RoleGrantsMatrixResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role_name: str
    grantable_roles: List[GrantableRole] = Field(default_factory=list)
