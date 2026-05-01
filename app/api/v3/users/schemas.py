"""User API schemas (request/response models)."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ....domain.users.division import DIVISION_CHOICES, DIVISION_OTHERS


# Allowed values for the user's status field. "inactive" is what soft-deleted
# users carry; admins can also set it manually via the Edit User flow.
_USER_STATUS_CHOICES = ("active", "inactive", "locked", "registered")


class UserCreateRequest(BaseModel):
    """Request schema for creating a user.

    Per product spec, every new user must have:
      - a vendor (single, FK to vendors)
      - a division (one of DIVISION_CHOICES; 'others' requires divisionOther)
      - at least one project mapping (project_ids)
    """
    model_config = ConfigDict(populate_by_name=True)

    login: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    firstName: Optional[str] = Field(None, max_length=255)
    lastName: Optional[str] = Field(None, max_length=255)
    admin: bool = False

    vendorId: str = Field(
        ..., alias="vendor_id",
        description="UUID of the vendor this user belongs to.",
    )
    division: str = Field(
        ...,
        description=f"One of: {', '.join(DIVISION_CHOICES)}.",
    )
    divisionOther: Optional[str] = Field(
        None, alias="division_other", max_length=255,
        description=(
            f"Required (non-empty) when division == '{DIVISION_OTHERS}'. "
            "Must be omitted / null for any other division."
        ),
    )
    projectIds: List[str] = Field(
        ...,
        alias="project_ids",
        min_length=1,
        description=(
            "List of project UUIDs to map this user to. At least one is "
            "required. Each id must reference a non-deleted project."
        ),
    )

    @field_validator("division")
    @classmethod
    def _validate_division(cls, v: str) -> str:
        if v not in DIVISION_CHOICES:
            raise ValueError(
                f"Division must be one of: {', '.join(DIVISION_CHOICES)}."
            )
        return v


class UserUpdateRequest(BaseModel):
    """Request schema for updating a user."""
    model_config = ConfigDict(populate_by_name=True)

    email: Optional[EmailStr] = None
    firstName: Optional[str] = Field(None, max_length=255)
    lastName: Optional[str] = Field(None, max_length=255)
    admin: Optional[bool] = None
    status: Optional[str] = None
    vendorId: Optional[str] = Field(None, alias="vendor_id")
    division: Optional[str] = None
    divisionOther: Optional[str] = Field(
        None, alias="division_other", max_length=255,
    )

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v):
        if v is not None and v not in _USER_STATUS_CHOICES:
            raise ValueError(
                f"Status must be one of: {', '.join(_USER_STATUS_CHOICES)}."
            )
        return v

    @field_validator("division")
    @classmethod
    def _validate_division(cls, v):
        if v is not None and v not in DIVISION_CHOICES:
            raise ValueError(
                f"Division must be one of: {', '.join(DIVISION_CHOICES)}."
            )
        return v


class UserPasswordUpdateRequest(BaseModel):
    """Request schema for updating user password."""
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    """Request schema for user login."""
    login: str
    password: str


class LoginResponse(BaseModel):
    """Response schema for user login."""
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None


class UserListQuery(BaseModel):
    """Query parameters for listing users."""
    offset: int = Field(1, ge=1, description="Page number (1-indexed)")
    pageSize: int = Field(20, ge=1, le=100, description="Number of items per page")
    status: Optional[str] = Field(None, description="Filter by status")
    includeDeleted: bool = Field(
        False, alias="include_deleted",
        description="Admin-only: also surface soft-deleted users.",
    )


class IntrospectRequest(BaseModel):
    """Request schema for token introspection.

    RFC 7662-style: pure read-only metadata lookup, never rotates tokens.
    Provide either or both fields. Both → response shape becomes
    ``{access: {...}, refresh: {...}}``.
    """

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class RefreshRequest(BaseModel):
    """Request schema for POST /users/refresh.

    Takes only a refresh token. Successful rotation returns a new
    access + refresh pair plus expiry metadata so the FE can schedule
    the next preemptive refresh without decoding the JWT.
    """

    refresh_token: str
