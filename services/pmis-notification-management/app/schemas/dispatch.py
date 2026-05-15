"""Templated dispatch schemas (Pydantic v2).

POST /notification/dispatch is the single canonical endpoint that internal
callers (e.g. user-svc) use to send a templated notification by
`template_kind`. notification-svc owns the catalog (cross-schema read of
masters.notification_templates per Q3) and the render logic; callers send
only the dispatch intent and the placeholder values.

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\schemas\\dispatch.py:1-43.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DispatchRequest(BaseModel):
    """Body of POST /notification/dispatch."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "channel": "email",
                "recipient": "alice@example.com",
                "template_kind": "otp_login",
                "payload": {"code": "123456", "ttl_seconds": 300},
                "user_id": "uuid-or-null",
            }
        },
    )

    channel: Literal["email", "sms"] = Field(..., description="Delivery channel")
    recipient: Annotated[
        str,
        Field(
            min_length=1,
            max_length=320,
            description="Email address (when channel=email) or E.164 phone (when channel=sms)",
        ),
    ]
    template_kind: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            description="Catalog template kind to render (e.g. 'otp_login', 'password_reset_link')",
        ),
    ]
    payload: Annotated[
        Dict[str, Any],
        Field(default_factory=dict, description="Placeholder values for the template"),
    ]
    user_id: Annotated[
        Optional[str],
        Field(default=None, description="Audit hint; opaque to notification-svc"),
    ]


class DispatchResponse(BaseModel):
    """Response of POST /notification/dispatch."""

    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(..., description="True if the provider accepted the message")
    message: str = Field(..., description="Human-readable status")
    provider: str = Field(..., description="Provider that handled the send")
    message_id: Optional[str] = Field(default=None, description="Provider-assigned message id, if any")
    channel: str = Field(..., description="email | sms — echoes the request")
    template_kind: str = Field(..., description="Template kind that was rendered")
    rendered_subject: Optional[str] = Field(
        default=None,
        description="Rendered email subject (None for SMS)",
    )
