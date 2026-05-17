"""OTP send/verify schemas (Q13 — storage owned by user-svc; dispatch by notification-svc)."""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import LoginResponse


class OtpSendRequest(BaseModel):
    """POST /user/users/login/send-otp."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ephemeral_token: Annotated[str, Field(min_length=1, description="Token returned by the prior login response")]
    channel: Literal["email", "sms"] = Field(default="email")


class OtpSendResponse(BaseModel):
    success: bool = True
    message: str = "OTP sent"
    channel: str
    masked_destination: Optional[str] = Field(default=None, description="e.g. a***@example.com or +91*****99")


class OtpVerifyRequest(BaseModel):
    """POST /user/users/login/verify-otp — completes login when 2FA was required."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ephemeral_token: Annotated[str, Field(min_length=1)]
    code: Annotated[str, Field(min_length=1, max_length=12, description="Numeric code received via email/SMS")]


# Verify returns a full LoginResponse on success — re-exported here for convenience.
OtpVerifyResponse = LoginResponse
