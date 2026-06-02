"""User CRUD schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas._base import ResponseModel


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
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # Convenience concat populated by the controller: ``first_name + " " +
    # last_name``, falling back to ``login`` when both names are empty.
    # Monolith parity — saves the FE from doing this concat on every row.
    full_name: Optional[str] = None
    status: str
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    division: Optional[str] = None
    division_label: Optional[str] = None
    division_other: Optional[str] = None
    phone_number: Optional[str] = None
    org_role: Optional[str] = None
    is_admin: bool = False
    is_super_admin: bool = False
    two_factor_enabled: bool = False
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
    """POST /users/create — matches VM UserCreateRequest field names."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", populate_by_name=True)

    login: Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")]
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=256)]

    # Name: VM sends full_name (single string), split server-side.
    # Alternatively first_name + last_name may be sent directly.
    full_name: Optional[str] = Field(default=None, max_length=510)
    first_name: Optional[str] = Field(default=None, max_length=64)
    last_name: Optional[str] = Field(default=None, max_length=64)

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

    @model_validator(mode="after")
    def _resolve_full_name(self):
        """Split full_name into first_name/last_name when those are absent."""
        if self.full_name and not self.first_name:
            parts = self.full_name.split(None, 1)
            object.__setattr__(self, "first_name", parts[0] if parts else None)
            object.__setattr__(self, "last_name", parts[1] if len(parts) > 1 else None)
        return self


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
    # VM sends fullName (camelCase); first_name/last_name also accepted.
    full_name: Optional[str] = Field(default=None, max_length=510)
    first_name: Optional[str] = Field(default=None, max_length=64)
    last_name: Optional[str] = Field(default=None, max_length=64)
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
