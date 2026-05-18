"""Auth-flow request/response schemas — login, refresh, introspect, logout."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas._base import ResponseModel


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    login: Annotated[str, Field(min_length=1, max_length=64, description="Username or email")]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class LoginUserSummary(BaseModel):
    """Bare-minimum user payload returned on a successful login."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    login: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool = Field(default=False)
    is_super_admin: bool = Field(default=False)
    permissions: List[str] = Field(default_factory=list)


class LoginResponse(BaseModel):
    """Successful login — flat token fields matching the VM wire shape.

    FE persistAuthFromPayload reads: access_token, refresh_token, user,
    and accessTokenExpiresAt (via readExpiresAt). Keep these at root level.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_at: Optional[datetime] = Field(
        default=None, serialization_alias="accessTokenExpiresAt"
    )
    refresh_token_expires_at: Optional[datetime] = Field(
        default=None, serialization_alias="refreshTokenExpiresAt"
    )
    user: Optional[LoginUserSummary] = None


class LoginOtpRequired(BaseModel):
    """Response when 2FA is required — the FE then posts to /login/send-otp."""

    requires_otp: bool = True
    ephemeral_token: str = Field(description="Opaque one-shot token tying this attempt to the OTP flow")
    channels_available: List[str] = Field(description="['email', 'sms'] for what the user can receive")


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class RefreshResponse(BaseModel):
    """Refresh response — monolith parity (round-8 fix).

    Matches PMIS-OpenProject/app/api/v3/users/services/refresh.py:176-189:
    flat keys `access_token`, `refresh_token`, `token_type`,
    `accessTokenExpiresAt`, `accessTokenIssuedAt`, `refreshTokenExpiresAt`,
    `refreshTokenIssuedAt`, `expiresInSeconds`, `user`.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_token_expires_at: datetime = Field(..., serialization_alias="accessTokenExpiresAt")
    access_token_issued_at: Optional[datetime] = Field(default=None, serialization_alias="accessTokenIssuedAt")
    refresh_token_expires_at: datetime = Field(..., serialization_alias="refreshTokenExpiresAt")
    refresh_token_issued_at: Optional[datetime] = Field(default=None, serialization_alias="refreshTokenIssuedAt")
    expires_in_seconds: Optional[int] = Field(default=None, serialization_alias="expiresInSeconds")
    user: Optional[LoginUserSummary] = None


class LogoutResponse(BaseModel):
    success: bool = True
    message: str = "Logged out"


class IntrospectRequest(BaseModel):
    """POST /user/users/introspect body — monolith parity (round-8 fix).

    Accepts EITHER `access_token` OR `refresh_token` OR both. Supplying
    both returns a `{access, refresh}` block; supplying one inlines the
    result at the root. At least one must be present.
    """

    model_config = ConfigDict(extra="forbid")
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class IntrospectTokenInfo(BaseModel):
    """Per-token introspection block — monolith parity with the keys
    from `_claims_to_response` in
    PMIS-OpenProject/app/api/v3/users/services/introspect.py:34-78.
    """

    model_config = ConfigDict(extra="allow")
    active: bool
    token_type: Optional[str] = Field(default=None, serialization_alias="tokenType")
    expired: bool = False
    sub: Optional[str] = None
    username: Optional[str] = None
    user_id: Optional[str] = Field(default=None, serialization_alias="userId")
    email: Optional[EmailStr] = None
    jti: Optional[str] = None
    iat: Optional[int] = None
    exp: Optional[int] = None
    issued_at: Optional[datetime] = Field(default=None, serialization_alias="issuedAt")
    expires_at: Optional[datetime] = Field(default=None, serialization_alias="expiresAt")
    is_admin: Optional[bool] = Field(default=None, serialization_alias="isAdmin")
    role: Optional[str] = None


class IntrospectResponse(BaseModel):
    """RFC-7662-shaped. Either inlines the per-token fields at the root
    (when one token was submitted) OR carries `{access, refresh}` blocks
    (when both were submitted). Monolith parity."""

    model_config = ConfigDict(extra="allow")
    # Inline single-token shape (mirrors IntrospectTokenInfo)
    active: Optional[bool] = None
    token_type: Optional[str] = Field(default=None, serialization_alias="tokenType")
    expired: Optional[bool] = None
    sub: Optional[str] = None
    username: Optional[str] = None
    user_id: Optional[str] = Field(default=None, serialization_alias="userId")
    email: Optional[EmailStr] = None
    jti: Optional[str] = None
    iat: Optional[int] = None
    exp: Optional[int] = None
    issued_at: Optional[datetime] = Field(default=None, serialization_alias="issuedAt")
    expires_at: Optional[datetime] = Field(default=None, serialization_alias="expiresAt")
    is_admin: Optional[bool] = Field(default=None, serialization_alias="isAdmin")
    role: Optional[str] = None
    # Both-tokens shape — set only when both were submitted.
    access: Optional[IntrospectTokenInfo] = None
    refresh: Optional[IntrospectTokenInfo] = None
