"""SMS request / response schemas (Pydantic v2).

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\schemas\\sms.py:1-25.
"""
from __future__ import annotations

from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class SMSRequest(BaseModel):
    """Body of POST /notification/sms/send."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "to": "+919999999999",
                "message": "Your PMIS appointment is confirmed.",
            }
        },
    )

    to: Annotated[
        str,
        Field(
            min_length=4,
            max_length=20,
            pattern=r"^\+?[0-9]{4,15}$",
            description="Recipient phone number in E.164 format (e.g. +919999999999)",
            examples=["+919999999999"],
        ),
    ]
    message: Annotated[
        str,
        Field(min_length=1, max_length=1600, description="SMS body (max 1600 chars; provider may segment)"),
    ]


class SMSResponse(BaseModel):
    """Response of POST /notification/sms/send."""

    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(..., description="True if the provider accepted the message")
    message: str = Field(..., description="Human-readable status")
    provider: str = Field(..., description="Name of the provider that handled the send (mock / twilio / msg91)")
    message_id: Optional[str] = Field(default=None, description="Provider-assigned message id, if any")
