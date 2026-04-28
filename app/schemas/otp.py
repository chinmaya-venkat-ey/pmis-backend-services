from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


class OTPChannel(str, Enum):
    sms = "sms"
    email = "email"


class OTPSendRequest(BaseModel):
    channel: OTPChannel
    destination: str = Field(
        ...,
        description="Phone number (E.164) for SMS or email address for email",
        examples=["+919999999999"],
    )
    purpose: Optional[str] = Field(default="verification", max_length=64)

    @model_validator(mode="after")
    def validate_destination(self) -> "OTPSendRequest":
        if self.channel == OTPChannel.email:
            # Re-use pydantic's EmailStr validation by constructing a model
            from pydantic import TypeAdapter
            TypeAdapter(EmailStr).validate_python(self.destination)
        else:
            if not self.destination.startswith("+") or not self.destination[1:].isdigit():
                raise ValueError("SMS destination must be in E.164 format, e.g. +919999999999")
        return self


class OTPSendResponse(BaseModel):
    success: bool
    message: str
    channel: OTPChannel
    destination: str
    expires_in_seconds: int
    request_id: str


class OTPVerifyRequest(BaseModel):
    channel: OTPChannel
    destination: str
    otp: str = Field(..., min_length=4, max_length=10)


class OTPVerifyResponse(BaseModel):
    success: bool
    message: str
    verified: bool
