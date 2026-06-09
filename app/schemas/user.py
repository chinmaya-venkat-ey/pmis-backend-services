"""User CRUD schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._base import ResponseModel
from app.schemas.role_assignment import RoleAssignmentSummary


class UserProjectSummary(ResponseModel):
    """Slim project shape embedded in a UserResponse.projects[]."""

    id: str
    project_code: Optional[str] = None
    name: str
    status: str


class UserResponse(ResponseModel):
    """Returned by GET /users, GET /users/{id}, etc."""

    id: str
    user_code: Optional[str] = None
    login: str
    email: EmailStr
    # The single canonical name field (stored on users.users.full_name).
    full_name: Optional[str] = None
    status: str
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    division: Optional[str] = None
    division_label: Optional[str] = None
    division_other: Optional[str] = None
    phone_number: Optional[str] = None
    # 2026-06-02: changed from Optional[str] to List[RoleAssignmentSummary].
    # A user can hold multiple role assignments scoped differently (e.g.
    # admin globally + project_member on project X). Each entry carries
    # role_name + scope + organization_id/project_id/project_code, so the
    # FE knows where each role applies. Auto-derived from the DB by
    # RbacRepository.builtin_role_assignments_for_user; the
    # users.users.org_role column itself stays as a legacy varchar hint
    # and is no longer surfaced here.
    org_role: List["RoleAssignmentSummary"] = Field(default_factory=list)
    is_admin: bool = False
    is_super_admin: bool = False
    two_factor_enabled: bool = False
    # Login audit (IST). previous_login_at is the "Last Login" the profile shows
    # (the session before the current one); last_login_at is the current login.
    last_login_at: Optional[datetime] = None
    previous_login_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    projects: List[UserProjectSummary] = Field(default_factory=list)


class UserProjectAssignmentInput(BaseModel):
    """Legacy local format for project_assignments[] on user create."""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    role_id: int


class UserCreateRequest(BaseModel):
    """POST /users/create — matches VM UserCreateRequest field names.

    Accepts both camelCase (``fullName``, the FE form) and snake_case
    (``full_name``) via the alias generator + populate_by_name — previously
    only snake_case was accepted on create, so a ``fullName`` was silently
    dropped and the new user had no name.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        alias_generator=lambda s: (
            "".join(w.capitalize() if i else w for i, w in enumerate(s.split("_")))
        ),
        populate_by_name=True,
    )

    login: Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")]
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=256)]

    # The single canonical name field.
    full_name: Optional[str] = Field(default=None, max_length=510)

    phone_number: Optional[str] = Field(default=None, max_length=50)
    vendor_id: Optional[str] = Field(default=None, max_length=36)
    division: Optional[str] = Field(default=None, max_length=64)
    division_other: Optional[str] = Field(default=None, max_length=255)

    # VM sends "orgRole" (camelCase); accept both via alias + populate_by_name.
    org_role: Optional[str] = Field(default=None, max_length=64, alias="orgRole")
    admin: bool = False
    two_factor_enabled: bool = False

    # Project mapping — VM sends project_ids; legacy local format also accepted.
    project_ids: Optional[List[str]] = Field(default=None)
    project_assignments: List[UserProjectAssignmentInput] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    """PATCH /users/{id} — partial update, matches VM UserUpdateRequest.

    Bug #14: FE sends a mix of camelCase (fullName, twoFactorEnabled) and
    snake_case (vendor_id, phone_number, division_other) keys. Using
    alias_generator=to_camel + populate_by_name=True accepts both forms.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        alias_generator=lambda s: (
            "".join(w.capitalize() if i else w for i, w in enumerate(s.split("_")))
        ),
        populate_by_name=True,
    )

    email: Optional[EmailStr] = None
    # VM sends fullName (camelCase) — the single canonical name field.
    full_name: Optional[str] = Field(default=None, max_length=510)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    vendor_id: Optional[str] = Field(default=None, max_length=36)
    division: Optional[str] = Field(default=None, max_length=64)
    division_other: Optional[str] = Field(default=None, max_length=255)
    org_role: Optional[str] = Field(default=None, max_length=64)
    admin: Optional[bool] = None
    two_factor_enabled: Optional[bool] = None
    status: Optional[str] = Field(default=None, max_length=16)
    # project_ids: None = leave unchanged, [] = clear, non-empty = replace
    project_ids: Optional[List[str]] = None


class UserPasswordUpdateRequest(BaseModel):
    """PATCH /users/{id}/password — field name matches VM ('password', not 'new_password')."""

    model_config = ConfigDict(extra="forbid")
    password: Annotated[str, Field(min_length=8, max_length=256)]


class UserCheckLoginResponse(BaseModel):
    login: str
    available: bool
