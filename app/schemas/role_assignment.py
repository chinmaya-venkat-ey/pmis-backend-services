"""Role-assignment schemas — Doc-41 scoped grants."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas._base import ResponseModel


class RoleAssignmentSummary(BaseModel):
    """Compact role-assignment shape for embedding under a user payload
    (login response, /users/me, /users list, etc.).

    Carries enough for the FE to:
      * know what the role is (``role_name`` + ``role_id``),
      * know where it applies (``scope`` + ``organization_id`` / ``project_id``),
      * render scoped labels without a second call (``project_code``),
      * call DELETE /role-assignments/{id} (``assignment_id``),
      * show audit info (``created_at`` + ``created_by``).

    2026-06-02: replaces the prior ``org_role: List[str]`` flat-names list.
    ``assignment_id`` is null for legacy ``user_roles`` rows (composite-PK
    table has no surrogate id) and an int for ``user_role_assignments``
    rows.
    """

    model_config = ConfigDict(from_attributes=True)
    role_name: str
    role_id: int
    scope: str = Field(description="'global' | 'org' | 'project'")
    organization_id: Optional[str] = None
    project_id: Optional[str] = None
    project_code: Optional[str] = None
    assignment_id: Optional[int] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class RoleAssignmentResponse(ResponseModel):
    """Returned by GET / POST role-assignment endpoints."""

    id: int
    user_id: str
    user_login: Optional[str] = None
    user_email: Optional[str] = None
    role_id: int
    role_name: str
    organization_id: Optional[str] = None
    project_id: Optional[str] = None
    # Human-readable display ID of the project this assignment is scoped to.
    # Populated when the row's scope is "project" (resolved via cross-schema
    # mirror); null for global / org-scoped grants. Lets the FE render the
    # Manage-Team page header without a separate /projects/{id} call.
    project_code: Optional[str] = None
    scope: str = Field(description="'global' | 'org' | 'project'")
    created_at: datetime
    created_by: Optional[str] = None


class RoleAssignmentCreateRequest(BaseModel):
    """POST /user/users/{id}/role-assignments/create or
        POST /user/projects/{uuid}/role-assignments/create.

    Exactly one of (`organization_id`, `project_id`, `project_ids`) may be
    set. `project_ids` enables batch creation across multiple projects in
    one call — the response then carries `{items: [...], total: N}`.

    `user_id` is required only on the user-scoped endpoint; on the
    project-scoped endpoint it's required in the body too.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    user_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    role_id: int
    organization_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    project_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    project_ids: List[str] = Field(default_factory=list, description="Batch project-scope create")

    @model_validator(mode="after")
    def validate_scope(self):
        scope_fields = (
            (self.organization_id is not None),
            (self.project_id is not None),
            (len(self.project_ids) > 0),
        )
        if sum(scope_fields) > 1:
            raise ValueError(
                "Exactly one of organization_id, project_id, project_ids may be set"
            )
        return self


class RoleAssignmentBatchResponse(BaseModel):
    """Returned for batch creates (`project_ids` was provided)."""

    items: List[RoleAssignmentResponse]
    total: int


class ProjectRolesBulkWriteRequest(BaseModel):
    """PUT /user/projects/{uuid}/role-assignments — bulk-replace for Manage-Team page.

    Each role_name listed is fully replaced (all existing assignments for that
    role+project are deleted, then the supplied user_ids are inserted).
    Roles not mentioned in the dict are left unchanged.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "assignments": {
                    "project_admin":  ["usr-0001"],
                    "project_member": ["usr-0002", "usr-0005"],
                }
            }
        },
    )
    assignments: Dict[str, List[str]] = Field(
        description=(
            "Map of role_name → user_id list. "
            "Each listed role is fully replaced. "
            "Roles not present are left unchanged."
        )
    )
