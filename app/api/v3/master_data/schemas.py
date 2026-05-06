"""Master-data request schemas — user-mgmt slim slice (doc 37 part 2).

Only the schemas backing endpoints user-management actually owns:
  - notification_templates (doc 36)

Roles + permissions delegate to the legacy /roles and /permissions
routes which carry their own schemas — no new shapes needed here.
"""
import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Notification templates (doc 36)
# ---------------------------------------------------------------------------
#
# Mirror of monolith's NotificationTemplateCreateRequest /
# NotificationTemplateUpdateRequest. Kept verbatim so the wire shapes
# stay identical when monolith proxies to user-service.

_CHANNEL_EMAIL = "email"
_CHANNEL_SMS = "sms"
_NOTIFICATION_CHANNELS = (_CHANNEL_EMAIL, _CHANNEL_SMS)

_ALLOWED_PLACEHOLDERS = {
    ("otp_login", _CHANNEL_EMAIL): {"code", "ttl_minutes"},
    ("otp_login", _CHANNEL_SMS): {"code", "ttl_minutes"},
    ("password_reset_link", _CHANNEL_EMAIL): {
        "reset_url", "token", "ttl_minutes",
    },
    ("password_reset_link", _CHANNEL_SMS): {"token", "ttl_minutes"},
    ("password_reset_otp", _CHANNEL_EMAIL): {"code", "ttl_minutes"},
    ("password_reset_otp", _CHANNEL_SMS): {"code", "ttl_minutes"},
}

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _extract_placeholders(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return _PLACEHOLDER_RE.findall(text)


def _validate_placeholder_set(
    *,
    template_kind: str,
    channel: str,
    subject: Optional[str],
    body: Optional[str],
) -> None:
    """Raise ``ValueError`` listing the offending names when the
    template references placeholders not in the allow-list for this
    (kind, channel). No-op on unknown kinds — caller-owned."""
    allowed = _ALLOWED_PLACEHOLDERS.get((template_kind, channel))
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
        if v not in _NOTIFICATION_CHANNELS:
            raise ValueError(
                f"channel must be one of {list(_NOTIFICATION_CHANNELS)}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _shape_check(self):
        if self.channel == _CHANNEL_EMAIL and not (self.subject or "").strip():
            raise ValueError("subject is required for email templates")
        if self.channel == _CHANNEL_SMS and (self.subject or "").strip():
            raise ValueError("subject must be omitted for sms templates")
        try:
            _validate_placeholder_set(
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
