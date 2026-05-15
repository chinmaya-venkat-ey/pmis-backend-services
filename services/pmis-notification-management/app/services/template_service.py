"""Template service — DB-backed renderer (Doc 38).

Looks up the active notification template by (template_kind, channel) in
masters.notification_templates (cross-schema mirror per Q3), computes
placeholders, runs `str.format_map` over the stored copy. Falls back to a
generic message when no active row matches — notifications must NEVER
crash the dispatch path even when the catalog is mis-edited.

Ported from
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\services\\template_service.py:1-158
with these changes:
  - Reads via NotificationTemplateRepository (SQLAlchemy 2.0 select())
    against the cross-schema mirror, not direct .query() on a local model.
  - Moved from module-level functions to a TemplateService class taking
    a Session in __init__ (matches Q8 "controllers + services" pattern).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories.notification_template_repository import NotificationTemplateRepository
from app.utilities.logger import get_logger

logger = get_logger(__name__)


# Channel + template-kind constants — string-coded, no enums.
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"
TEMPLATE_OTP_LOGIN = "otp_login"
TEMPLATE_PASSWORD_RESET_LINK = "password_reset_link"
TEMPLATE_PASSWORD_RESET_OTP = "password_reset_otp"


# Generic fallback — used when no active row matches.
_FALLBACK_EMAIL_SUBJECT = "PMIS notification"
_FALLBACK_EMAIL_BODY = (
    "<p>You have a notification from PMIS. Sign in to your account "
    "for details.</p>"
)
_FALLBACK_SMS_BODY = "You have a PMIS notification. Sign in for details."


def _compute_placeholders(template_kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build the dict passed to `str.format` from the raw dispatch payload."""
    p: Dict[str, Any] = {}
    if template_kind in (TEMPLATE_OTP_LOGIN, TEMPLATE_PASSWORD_RESET_OTP):
        p["code"] = (
            payload.get("code")
            or payload.get("reset_token")
            or payload.get("token", "")
        )
        ttl_seconds = int(
            payload.get("ttl_seconds")
            or (300 if template_kind == TEMPLATE_OTP_LOGIN else 3600)
        )
        p["ttl_minutes"] = max(1, ttl_seconds // 60)
    elif template_kind == TEMPLATE_PASSWORD_RESET_LINK:
        token = payload.get("reset_token") or payload.get("token", "")
        p["token"] = token
        ttl_seconds = int(payload.get("ttl_seconds") or 3600)
        p["ttl_minutes"] = max(1, ttl_seconds // 60)
        fe_base = (settings.frontend_base_url or "").rstrip("/")
        p["reset_url"] = (
            f"{fe_base}/reset-password?token={token}" if (fe_base and token) else ""
        )
    else:
        # Unknown kind: forward raw payload values for caller-defined templates.
        if "ttl_seconds" in payload:
            try:
                p["ttl_minutes"] = max(1, int(payload["ttl_seconds"]) // 60)
            except (TypeError, ValueError):
                pass
        for k, v in payload.items():
            if k not in p:
                p[k] = v
    return p


class _SafeDict(dict):
    """`str.format_map` substrate that returns "" for missing keys."""

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return ""


def _safe_format(text: Optional[str], placeholders: Dict[str, Any]) -> str:
    if not text:
        return ""
    try:
        return text.format_map(_SafeDict(placeholders))
    except (ValueError, IndexError) as exc:
        logger.warning("Template format failed: %s. Using raw text.", exc)
        return text


class TemplateService:
    """Renders notification templates by template_kind + channel."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationTemplateRepository(db)

    def render_email(
        self, template_kind: str, payload: Dict[str, Any]
    ) -> Tuple[str, str, bool]:
        """Return (subject, body, is_html). Falls back to generic when missing."""
        row = self.repo.find_active(template_kind=template_kind, channel=CHANNEL_EMAIL)
        if row is None:
            logger.warning(
                "No active email notification_template for kind=%r; using fallback.",
                template_kind,
            )
            return _FALLBACK_EMAIL_SUBJECT, _FALLBACK_EMAIL_BODY, True
        placeholders = _compute_placeholders(template_kind, payload)
        return (
            _safe_format(row.subject, placeholders) or _FALLBACK_EMAIL_SUBJECT,
            _safe_format(row.body, placeholders),
            bool(row.is_html),
        )

    def render_sms(self, template_kind: str, payload: Dict[str, Any]) -> str:
        """Return the SMS body. Falls back to generic when missing."""
        row = self.repo.find_active(template_kind=template_kind, channel=CHANNEL_SMS)
        if row is None:
            logger.warning(
                "No active sms notification_template for kind=%r; using fallback.",
                template_kind,
            )
            return _FALLBACK_SMS_BODY
        placeholders = _compute_placeholders(template_kind, payload)
        return _safe_format(row.body, placeholders)
