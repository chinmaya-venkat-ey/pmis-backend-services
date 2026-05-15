"""Email request / response schemas (Pydantic v2).

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\schemas\\email.py:1-31
with v2 ConfigDict + Annotated/Field metadata applied per PLAN.md §2.2.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmailRequest(BaseModel):
    """Body of POST /notification/email/send."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "to": ["user@example.com"],
                "subject": "Welcome to PMIS",
                "body": "<h1>Hello</h1><p>Welcome to the PMIS portal.</p>",
                "is_html": True,
            }
        },
    )

    to: Annotated[
        List[EmailStr],
        Field(min_length=1, description="Recipient email addresses (at least one)"),
    ]
    subject: Annotated[
        str,
        Field(min_length=1, max_length=255, description="Email subject line"),
    ]
    body: Annotated[
        str,
        Field(min_length=1, description="Plain text or HTML body"),
    ]
    is_html: Annotated[bool, Field(default=False, description="If true, body is rendered as HTML")]
    cc: Annotated[Optional[List[EmailStr]], Field(default=None, description="CC addresses (optional)")]
    bcc: Annotated[Optional[List[EmailStr]], Field(default=None, description="BCC addresses (optional)")]


class EmailResponse(BaseModel):
    """Response of POST /notification/email/send."""

    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(..., description="True if the provider accepted the message")
    message: str = Field(..., description="Human-readable status")
    provider: str = Field(..., description="Name of the provider that handled the send (smtp / sendgrid)")
    message_id: Optional[str] = Field(default=None, description="Provider-assigned message id, if any")
