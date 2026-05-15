"""Role-assignment schemas — Doc-41 scoped grants."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RoleAssignmentResponse(BaseModel):
    """Returned by GET / POST role-assignment endpoints."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: str
    user_login: Optional[str] = None
    user_email: Optional[str] = None
    role_id: int
    role_name: str
    organization_id: Optional[str] = None
    project_id: Optional[str] = None
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
