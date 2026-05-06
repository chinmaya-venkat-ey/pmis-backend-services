"""Template service — DB-backed renderer (doc 38).

Same logic that lived in user-service's ``app/shared/notifications.py``,
moved here verbatim. Looks up the active template by
``(template_kind, channel)``, computes placeholders, runs
``str.format_map`` over the stored copy. When no active row matches,
returns a generic fallback (plus a warning log).

Notifications must NEVER crash the dispatch path even when the
catalog has been mis-edited or seeds haven't run.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import settings
from ..db.models.notification_template import NotificationTemplateModel


logger = logging.getLogger(__name__)


# Channel + template-kind constants — kept as strings (no enum overhead).
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


def _setting(*names: str, default: Any = None) -> Any:
    """Settings attribute lookup with fallback to legacy lower-case names."""
    for n in names:
        if hasattr(settings, n):
            v = getattr(settings, n)
            if v is not None and v != "":
                return v
    return default


def _compute_placeholders(template_kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build the dict passed to ``str.format`` from the raw dispatch payload."""
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
        fe_base = (_setting("frontend_base_url", "FRONTEND_BASE_URL", default="") or "").rstrip("/")
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
    """``str.format_map`` substrate that returns ``""`` for missing keys."""

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return ""


def _safe_format(text: Optional[str], placeholders: Dict[str, Any]) -> str:
    if not text:
        return ""
    try:
        return text.format_map(_SafeDict(placeholders))
    except (ValueError, IndexError) as e:
        logger.warning(
            "notification template format failed: %s. Using raw text.", e,
        )
        return text


def _lookup_template(
    db: Session, *, template_kind: str, channel: str,
) -> Optional[NotificationTemplateModel]:
    return (
        db.query(NotificationTemplateModel)
        .filter(NotificationTemplateModel.template_kind == template_kind)
        .filter(NotificationTemplateModel.channel == channel)
        .filter(NotificationTemplateModel.active.is_(True))
        .order_by(NotificationTemplateModel.id.desc())
        .first()
    )


def render_email(
    db: Session, template_kind: str, payload: Dict[str, Any]
) -> Tuple[str, str, bool]:
    """Return ``(subject, body, is_html)`` for the email channel.

    Falls back to a generic subject + body when no active row matches.
    Never raises.
    """
    row = _lookup_template(db, template_kind=template_kind, channel=CHANNEL_EMAIL)
    if row is None:
        logger.warning(
            "No active email notification_template for kind=%r; sending fallback.",
            template_kind,
        )
        return _FALLBACK_EMAIL_SUBJECT, _FALLBACK_EMAIL_BODY, True
    placeholders = _compute_placeholders(template_kind, payload)
    return (
        _safe_format(row.subject, placeholders) or _FALLBACK_EMAIL_SUBJECT,
        _safe_format(row.body, placeholders),
        bool(row.is_html),
    )


def render_sms(
    db: Session, template_kind: str, payload: Dict[str, Any]
) -> str:
    """Return the SMS body. Falls back to a generic message when no
    active row matches."""
    row = _lookup_template(db, template_kind=template_kind, channel=CHANNEL_SMS)
    if row is None:
        logger.warning(
            "No active sms notification_template for kind=%r; sending fallback.",
            template_kind,
        )
        return _FALLBACK_SMS_BODY
    placeholders = _compute_placeholders(template_kind, payload)
    return _safe_format(row.body, placeholders)
