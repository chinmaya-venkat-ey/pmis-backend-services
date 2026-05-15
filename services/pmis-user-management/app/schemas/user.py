"""User CRUD schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserProjectSummary(BaseModel):
    """Slim project shape embedded in a UserResponse.projects[]."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    project_code: Optional[str] = None
    name: str
    status: str


class UserResponse(BaseModel):
    """Returned by GET /user/users/list, GET /user/users/{id}/details, etc."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    user_code: Optional[str] = None
    login: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: str
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    division: Optional[str] = None
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
    """Doc-44: project_assignments[] on user create — assigns the new user
    to N projects with a given role in one shot."""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    role_id: int


class UserCreateRequest(BaseModel):
    """POST /user/users/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    login: Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")]
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=256)]
    first_name: Annotated[Optional[str], Field(default=None, max_length=64)]
    last_name: Annotated[Optional[str], Field(default=None, max_length=64)]
    phone_number: Annotated[Optional[str], Field(default=None, max_length=32)]
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    division: Annotated[Optional[str], Field(default=None, max_length=64)]
    division_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    org_role: Annotated[Optional[str], Field(default=None, max_length=64,
                                              description="Doc-45 FE-label cache")]
    two_factor_enabled: bool = False
    project_assignments: List[UserProjectAssignmentInput] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    """PATCH /user/users/{id}/update — partial."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    email: Annotated[Optional[EmailStr], Field(default=None)]
    first_name: Annotated[Optional[str], Field(default=None, max_length=64)]
    last_name: Annotated[Optional[str], Field(default=None, max_length=64)]
    phone_number: Annotated[Optional[str], Field(default=None, max_length=32)]
    vendor_id: Annotated[Optional[str], Field(default=None, max_length=36)]
    division: Annotated[Optional[str], Field(default=None, max_length=64)]
    division_other: Annotated[Optional[str], Field(default=None, max_length=255)]
    org_role: Annotated[Optional[str], Field(default=None, max_length=64)]
    two_factor_enabled: Annotated[Optional[bool], Field(default=None)]
    status: Annotated[Optional[str], Field(default=None, max_length=16,
                                            description="Used by USERS_DEACTIVATE-only callers")]


class UserPasswordUpdateRequest(BaseModel):
    """PATCH /user/users/{id}/password/update — admin sets a user's password."""

    model_config = ConfigDict(extra="forbid")
    new_password: Annotated[str, Field(min_length=12, max_length=256)]


class UserCheckLoginResponse(BaseModel):
    login: str
    available: bool
