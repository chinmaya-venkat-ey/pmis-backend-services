"""Auth-flow request/response schemas — login, refresh, introspect, logout."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    login: Annotated[str, Field(min_length=1, max_length=64, description="Username or email")]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class TokenPair(BaseModel):
    """Embedded in LoginResponse / RefreshResponse."""

    model_config = ConfigDict(from_attributes=True)
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime


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
    """Successful login (no 2FA required)."""

    model_config = ConfigDict(from_attributes=True)
    tokens: TokenPair
    user: LoginUserSummary


class LoginOtpRequired(BaseModel):
    """Response when 2FA is required — the FE then posts to /login/send-otp."""

    requires_otp: bool = True
    ephemeral_token: str = Field(description="Opaque one-shot token tying this attempt to the OTP flow")
    channels_available: List[str] = Field(description="['email', 'sms'] for what the user can receive")


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class RefreshResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tokens: TokenPair


class LogoutResponse(BaseModel):
    success: bool = True
    message: str = "Logged out"


class IntrospectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str


class IntrospectResponse(BaseModel):
    """RFC-7662-shaped token-introspection response."""

    model_config = ConfigDict(extra="allow")
    active: bool
    expired: bool = False
    user_id: Optional[str] = None
    sub: Optional[str] = None
    email: Optional[EmailStr] = None
    jti: Optional[str] = None
    iat: Optional[int] = None
    exp: Optional[int] = None
