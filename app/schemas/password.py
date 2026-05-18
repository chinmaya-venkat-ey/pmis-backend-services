"""Password reset request/response schemas."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ForgotPasswordRequest(BaseModel):
    """POST /users/forgot-password.

    Anti-enumeration: route ALWAYS returns 200 with a generic success message
    regardless of whether the email/login exists.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    login_or_email: Annotated[str, Field(min_length=1, max_length=255, description="Username or email")]
    channel: Literal["email", "sms"] = Field(default="email", description="Delivery channel")


class ForgotPasswordResponse(BaseModel):
    success: bool = True
    message: str = "If an account exists, reset instructions have been sent"


class ResetPasswordRequest(BaseModel):
    """POST /users/reset-password — consumes a single-use token."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    token_or_code: Annotated[str, Field(min_length=1, description="Token from the reset email or OTP from SMS")]
    new_password: Annotated[str, Field(min_length=8, max_length=256)]


class ResetPasswordResponse(BaseModel):
    success: bool = True
    message: str = "Password reset"
