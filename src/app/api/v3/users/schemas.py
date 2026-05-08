"""
User API schemas (request/response models).
"""
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ....domain.resource_types.resource_type import (
    DIVISION_CHOICES,
    DIVISION_OTHERS,
)


# Allowed values for the user's status field. "inactive" is what soft-deleted
# users carry; admins can also set it manually via the Edit User flow.
_USER_STATUS_CHOICES = ("active", "inactive", "locked", "registered")


class UserCreateRequest(BaseModel):
    """Request schema for creating a user.

    Per product spec, every new user must have:
      - a vendor (single, FK to vendors)
      - a division (one of DIVISION_CHOICES; 'others' requires divisionOther)
      - at least one project mapping (project_ids)

    The bootstrap admin path (init_db seed) bypasses this validation.
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
        description=(
            "Vendor identifier. Accepts EITHER the vendor's UUID OR its "
            "human-readable ``vendorCode`` (e.g. ``VN-ACME-260502143015`` "
            "— see doc 25). The dispatcher auto-detects via the ``VN-`` "
            "prefix; the persisted FK is always the canonical UUID."
        ),
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
    phoneNumber: str = Field(
        ...,
        alias="phone_number",
        min_length=1,
        max_length=50,
        description=(
            "User's phone / mobile number. Required on create. Free-form "
            "string (no regex check — international formats vary; FE may "
            "apply its own client-side mask). Mirrors the vendor schema's "
            "``phoneNumber`` field exactly."
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
    vendorId: Optional[str] = Field(
        None, alias="vendor_id",
        description=(
            "Vendor identifier. Accepts UUID or ``VN-...`` code (doc 25)."
        ),
    )
    division: Optional[str] = None
    divisionOther: Optional[str] = Field(
        None, alias="division_other", max_length=255,
    )
    phoneNumber: Optional[str] = Field(
        None,
        alias="phone_number",
        max_length=50,
        description=(
            "Optional on PATCH. When supplied, replaces the user's stored "
            "phone number; omit / null to leave unchanged. Mirrors the "
            "vendor PATCH schema."
        ),
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


# ---------------------------------------------------------------------------
# Doc 33 change 3 — 2FA + forgot-password schemas
# ---------------------------------------------------------------------------

class OtpSendRequest(BaseModel):
    """POST /users/login/send-otp body."""

    ephemeral_token: str = Field(..., min_length=10)
    channel: str = Field(..., description="email or sms")


class OtpVerifyRequest(BaseModel):
    """POST /users/login/verify-otp body."""

    ephemeral_token: str = Field(..., min_length=10)
    code: str = Field(..., min_length=4, max_length=12)


class ForgotPasswordRequest(BaseModel):
    """POST /users/forgot-password body. Anti-enumeration: this endpoint
    always returns 200, whether the user exists or not."""

    login_or_email: str = Field(..., min_length=1, max_length=255)
    channel: str = Field(..., description="email or sms")


class ResetPasswordRequest(BaseModel):
    """POST /users/reset-password body. Accepts either a URL-safe token
    (email channel) or a numeric OTP (sms channel) — the server hashes
    and matches whichever form was sent."""

    token_or_code: str = Field(..., min_length=4, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=255)
