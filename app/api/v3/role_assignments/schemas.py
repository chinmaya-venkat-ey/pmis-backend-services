"""Pydantic schemas for role-assignment endpoints (doc 41).

Keep the wire shape minimal: ``roleId`` references the canonical
roles table, scope is exactly one of ``organizationId`` or
``projectId`` (the other MUST be omitted / null). Validation in the
service layer additionally checks the role exists and the caller is
authorized to grant it.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoleAssignmentCreateRequest(BaseModel):
    """Body for POST /users/{id}/role-assignments and /projects/{id}/role-assignments.

    Exactly one scope field MUST be set (or both omitted to mean
    global scope, which is super-admin-only). The route-level path
    parameter (``project_id`` / ``vendor_id``) takes precedence over
    the body when present — the body's scope fields are still
    accepted for completeness but the path wins.
    """
    model_config = ConfigDict(populate_by_name=True)

    roleId: int = Field(..., alias="role_id", description="Role to grant.")
    organizationId: Optional[str] = Field(
        None, alias="organization_id",
        description="Vendor (= organization) UUID. Mutually exclusive with projectId.",
    )
    projectId: Optional[str] = Field(
        None, alias="project_id",
        description="Project UUID. Mutually exclusive with organizationId.",
    )
    # Optional userId — only honoured by the project-level POST
    # (where the path doesn't carry the target user). The user-level
    # POST ignores this field (path's user_id is canonical).
    userId: Optional[str] = Field(
        None, alias="user_id",
        description="Target user UUID. Required on /projects/{id}/role-assignments; ignored on /users/{id}/role-assignments.",
    )

    @model_validator(mode="after")
    def _validate_single_scope(self):
        if self.organizationId and self.projectId:
            raise ValueError(
                "organizationId and projectId are mutually exclusive — "
                "an assignment is either org-scoped, project-scoped, or global."
            )
        return self


class RoleAssignmentResponse(BaseModel):
    """Wire shape returned to the FE."""
    id: int
    userId: str
    userLogin: Optional[str] = None
    userEmail: Optional[str] = None
    roleId: int
    roleName: str
    organizationId: Optional[str] = None
    projectId: Optional[str] = None
    scope: str = Field(
        ..., description="One of 'global', 'org', 'project' — derived.",
    )
    createdAt: Optional[str] = None
    createdBy: Optional[str] = None


class ProjectRoleBucket(BaseModel):
    """Per-role group for the per-project drill-down view (the FE mock).

    Powers the table: Roles | Users where each role is a group with
    the list of users holding that role on the project.
    """
    roleId: int
    roleName: str
    users: List[dict]  # [{id, login, email, firstName, lastName}]


class ProjectRoleAssignmentsView(BaseModel):
    """Wrapping shape for the per-project drill-down."""
    projectId: str
    projectName: Optional[str] = None
    roles: List[ProjectRoleBucket]


class VendorProjectRow(BaseModel):
    """Single row in the Org-Mgmt landing view."""
    projectId: str
    projectName: Optional[str] = None
    projectStatus: Optional[str] = None
    roleAssignments: Optional[List[ProjectRoleBucket]] = None


class VendorProjectsView(BaseModel):
    vendorId: str
    vendorName: Optional[str] = None
    projects: List[VendorProjectRow]


class UserProjectRow(BaseModel):
    """Row in the User-Mgmt landing view (per-user project list)."""
    projectId: str
    projectName: Optional[str] = None
    roles: List[str]  # role names the user holds on this project


class UserProjectsView(BaseModel):
    userId: str
    userLogin: Optional[str] = None
    projects: List[UserProjectRow]
