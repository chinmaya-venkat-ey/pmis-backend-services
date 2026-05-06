"""Notification template schemas (doc 38)."""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Channel + placeholder allow-list (doc 36 — moved here from user-service)
# ---------------------------------------------------------------------------

CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"
NOTIFICATION_CHANNELS = (CHANNEL_EMAIL, CHANNEL_SMS)

ALLOWED_PLACEHOLDERS = {
    ("otp_login", CHANNEL_EMAIL): {"code", "ttl_minutes"},
    ("otp_login", CHANNEL_SMS): {"code", "ttl_minutes"},
    ("password_reset_link", CHANNEL_EMAIL): {"reset_url", "token", "ttl_minutes"},
    ("password_reset_link", CHANNEL_SMS): {"token", "ttl_minutes"},
    ("password_reset_otp", CHANNEL_EMAIL): {"code", "ttl_minutes"},
    ("password_reset_otp", CHANNEL_SMS): {"code", "ttl_minutes"},
}

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _extract_placeholders(text: Optional[str]) -> List[str]:
    return _PLACEHOLDER_RE.findall(text or "")


def validate_placeholder_set(
    *,
    template_kind: str,
    channel: str,
    subject: Optional[str],
    body: Optional[str],
) -> None:
    """Raise ``ValueError`` listing bad placeholders for known kinds.
    No-op on unknown kinds (free-form support)."""
    allowed = ALLOWED_PLACEHOLDERS.get((template_kind, channel))
    if allowed is None:
        return
    used = set(_extract_placeholders(subject)) | set(_extract_placeholders(body))
    bad = sorted(used - allowed)
    if bad:
        raise ValueError(
            f"Unknown placeholder(s) for kind '{template_kind}' on "
            f"channel '{channel}': {', '.join(bad)}. "
            f"Allowed: {sorted(allowed)}."
        )


# ---------------------------------------------------------------------------
# Pydantic shapes
# ---------------------------------------------------------------------------

class NotificationTemplateCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    templateKind: str = Field(
        ..., alias="template_kind", min_length=1, max_length=64,
    )
    channel: str = Field(...)
    subject: Optional[str] = Field(None, max_length=500)
    body: str = Field(..., min_length=1)
    isHtml: Optional[bool] = Field(None, alias="is_html")
    description: Optional[str] = Field(None, max_length=1024)
    active: bool = Field(True)

    @field_validator("channel")
    @classmethod
    def _channel_known(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in NOTIFICATION_CHANNELS:
            raise ValueError(
                f"channel must be one of {list(NOTIFICATION_CHANNELS)}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _shape_check(self):
        if self.channel == CHANNEL_EMAIL and not (self.subject or "").strip():
            raise ValueError("subject is required for email templates")
        if self.channel == CHANNEL_SMS and (self.subject or "").strip():
            raise ValueError("subject must be omitted for sms templates")
        try:
            validate_placeholder_set(
                template_kind=self.templateKind,
                channel=self.channel,
                subject=self.subject,
                body=self.body,
            )
        except ValueError as e:
            raise ValueError(str(e))
        return self


class NotificationTemplateUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    subject: Optional[str] = Field(None, max_length=500)
    body: Optional[str] = Field(None, min_length=1)
    isHtml: Optional[bool] = Field(None, alias="is_html")
    description: Optional[str] = Field(None, max_length=1024)
    active: Optional[bool] = None


class NotificationTemplateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    templateKind: str = Field(alias="template_kind")
    channel: str
    subject: Optional[str]
    body: str
    isHtml: bool = Field(alias="is_html")
    isBuiltin: bool = Field(alias="is_builtin")
    active: bool
    description: Optional[str]
