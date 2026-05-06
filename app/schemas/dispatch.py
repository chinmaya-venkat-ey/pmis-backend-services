"""Templated dispatch schema (doc 38 phase 2).

Single endpoint shape used by user-mgmt (and any other service) to fire
a notification by ``template_kind`` rather than wiring its own renderer.
The notification-service owns the template catalog + the render logic;
callers send only the dispatch intent and the placeholder values.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class DispatchRequest(BaseModel):
    channel: Literal["email", "sms"]
    recipient: str = Field(..., min_length=1, description="Email or E.164 phone")
    template_kind: str = Field(..., min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = Field(default=None, description="Audit hint; opaque")

    model_config = {
        "json_schema_extra": {
            "example": {
                "channel": "email",
                "recipient": "alice@example.com",
                "template_kind": "otp_login",
                "payload": {"code": "123456", "ttl_seconds": 300},
                "user_id": "uuid-or-null",
            }
        }
    }


class DispatchResponse(BaseModel):
    success: bool
    message: str
    provider: str
    message_id: Optional[str] = None
    channel: str
    template_kind: str
    rendered_subject: Optional[str] = None
