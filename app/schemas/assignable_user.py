"""Assignable-user schemas — wire surface for
``GET /project/projects/{uuid}/assignable-users``.

The picker shows the union of (a) project-tier role holders on this
project AND (b) org_admin holders on the project's owning vendor(s),
minus anyone holding an admin / super_admin tier (admins don't appear
in project pickers).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssignableUser(BaseModel):
    """One picker entry."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    login: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    org_role: Optional[str] = None


class AssignableUsersResponse(BaseModel):
    """``GET /project/projects/{uuid}/assignable-users`` payload."""

    model_config = ConfigDict(from_attributes=False)

    project_id: str
    project_name: str
    users: List[AssignableUser] = Field(default_factory=list)


class ProjectRoleAssignmentBucket(BaseModel):
    """One row of the role-assignments listing — one role + its members."""

    model_config = ConfigDict(from_attributes=False)

    role_id: int
    role_name: str
    users: List[dict] = Field(default_factory=list)


class ProjectRoleAssignmentsResponse(BaseModel):
    """``GET /project/projects/{uuid}/role-assignments`` payload."""

    model_config = ConfigDict(from_attributes=False)

    project_id: str
    project_name: str
    roles: List[ProjectRoleAssignmentBucket] = Field(default_factory=list)
