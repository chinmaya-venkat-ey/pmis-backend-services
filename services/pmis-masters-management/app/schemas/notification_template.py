"""Pydantic v2 schemas for the notification_templates catalog (moved here per Q3).

Templates are uniquely keyed by (template_kind, channel). Subject is required
for email channel; SMS templates omit subject. Placeholder validation
(matching the placeholders used in the template body to a known list) is
intentionally NOT done here — it lives in notification-svc's template_service,
which is the consumer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotificationTemplateCreateRequest(BaseModel):
    """Body of POST /masters/notification-templates/create."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    template_kind: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$",
              description="Catalog key, e.g. 'otp_login', 'password_reset_link'"),
    ]
    channel: Literal["email", "sms"]
    subject: Annotated[
        Optional[str],
        Field(default=None, max_length=500,
              description="Required when channel=email; ignored for sms"),
    ]
    body: Annotated[str, Field(min_length=1, description="Template body (str.format_map placeholders)")]
    is_html: bool = Field(default=True, description="Email-channel: render as HTML")
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]

    @model_validator(mode="after")
    def email_requires_subject(self):
        if self.channel == "email" and not self.subject:
            raise ValueError("subject is required when channel='email'")
        return self


class NotificationTemplateUpdateRequest(BaseModel):
    """Body of PATCH /masters/notification-templates/{template_id}/update — partial.

    `template_kind` and `channel` are immutable; create a new row + retire the old
    if you need to change the catalog key.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    subject: Annotated[Optional[str], Field(default=None, max_length=500)]
    body: Annotated[Optional[str], Field(default=None, min_length=1)]
    is_html: Annotated[Optional[bool], Field(default=None)]
    active: Annotated[Optional[bool], Field(default=None)]
    description: Annotated[Optional[str], Field(default=None, max_length=1024)]


class NotificationTemplateResponse(BaseModel):
    """Returned by GET /masters/notification-templates/list and /details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    template_kind: str
    channel: str
    subject: Optional[str] = None
    body: str
    is_html: bool
    is_builtin: bool
    active: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
