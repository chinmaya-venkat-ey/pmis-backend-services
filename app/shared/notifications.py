"""Notification client (doc 33 change 3 + doc 33 follow-up + doc 36).

Two backends behind one ``NotificationClient`` interface:

- ``MockNotificationClient`` — writes to the ``notification_log`` table
  and returns. The terminal sink during dev/tests; never makes a real
  HTTP call. Inspecting the table reveals every notification that
  would have been sent, with the recipient, channel, and template kind.

- ``HttpNotificationClient`` — POSTs to the live notification
  microservice (https://github.com/EY-DIGIT/PMIS-notification-service).
  Calls ``POST {NOTIFICATION_SERVICE_URL}/api/v1/notifications/email/send``
  for ``email`` channel and ``POST .../sms/send`` for ``sms``. The audit
  row is written first as ``queued``, then patched to ``sent`` (or
  ``failed`` with the error message) once the call returns.

Selection happens via the ``NOTIFICATION_CLIENT`` env var:
  - ``mock`` (default in dev/tests)
  - ``http`` (production / staging — needs ``NOTIFICATION_SERVICE_URL``)

Construct via the factory ``get_notification_client(db)`` — it picks
the backend based on settings and hands back an instance bound to the
provided session. Callers don't need to know which backend won.

The audit row is the source of truth for "did the system attempt to
notify?" — both backends write one before any external call. If the
HTTP call fails, the row is updated to ``status="failed"`` with the
error message so investigations can see exactly what was tried.

Doc 36 — DB-backed templates: ``_render_email`` and ``_render_sms``
look up the active row in ``notification_templates`` by
``(template_kind, channel)`` and ``str.format(**placeholders)`` over
the stored copy. Computed placeholders (``ttl_minutes`` from
``ttl_seconds``, ``reset_url`` from ``FRONTEND_BASE_URL`` + ``token``)
are derived in this module before substitution. When no active row
matches, the renderer falls back to a generic body and logs a warning
— notifications must not crash the auth flow even when the catalog
has been mis-edited.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from ..core.config import settings
from ..infrastructure.db.models.notification_log import NotificationLogModel
from ..infrastructure.db.models.notification_template import (
    NotificationTemplateModel,
)


logger = logging.getLogger(__name__)


# Channel constants (kept as strings — short list, no enum overhead).
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"

# Template kinds.
TEMPLATE_OTP_LOGIN = "otp_login"
TEMPLATE_PASSWORD_RESET_LINK = "password_reset_link"
TEMPLATE_PASSWORD_RESET_OTP = "password_reset_otp"


# Generic fallback strings used when the DB lookup misses (no active row
# for the requested kind+channel). Logs a warning so ops sees that
# templates need attention; never crashes the dispatch path.
_FALLBACK_EMAIL_SUBJECT = "PMIS notification"
_FALLBACK_EMAIL_BODY = (
    "<p>You have a notification from PMIS. Sign in to your account "
    "for details.</p>"
)
_FALLBACK_SMS_BODY = "You have a PMIS notification. Sign in for details."


# HTTP timeouts when calling the live notification microservice. Short
# connect timeout so a stuck DNS / unreachable host fails fast and
# doesn't block the auth flow; longer read timeout for legitimate slow
# email-provider hops (SendGrid / SMTP relays).
_HTTP_CONNECT_TIMEOUT = 5.0
_HTTP_READ_TIMEOUT = 15.0


class NotificationClient(ABC):
    """Contract every backend implements."""

    def __init__(self, db: Session):
        self.db = db

    @abstractmethod
    def send(
        self,
        *,
        user_id: Optional[str],
        channel: str,
        recipient: str,
        template_kind: str,
        payload: Dict[str, Any],
    ) -> NotificationLogModel:
        """Dispatch a notification + persist the audit row.

        Returns the persisted row so callers can correlate (e.g. for
        tests asserting the dispatch happened). The row is committed
        before this returns — callers don't need to commit separately.
        """
        raise NotImplementedError


class MockNotificationClient(NotificationClient):
    """Dev / test backend — terminal sink in the ``notification_log``."""

    def send(
        self,
        *,
        user_id: Optional[str],
        channel: str,
        recipient: str,
        template_kind: str,
        payload: Dict[str, Any],
    ) -> NotificationLogModel:
        row = NotificationLogModel(
            user_id=user_id,
            channel=channel,
            recipient=recipient,
            template_kind=template_kind,
            payload=payload,
            status="sent",  # mock pretends it sent
            error=None,
        )
        self.db.add(row)
        self.db.flush()
        self.db.commit()
        return row


# ---------------------------------------------------------------------------
# Email + SMS template renderers (doc 36 — DB-backed)
#
# ``_render_email`` and ``_render_sms`` look up the active template row
# from ``notification_templates`` by ``(template_kind, channel)`` and
# ``str.format(**placeholders)`` over the stored copy. Computed
# placeholders (``ttl_minutes``, ``reset_url``) are derived from the
# raw ``payload`` before substitution. The stored template only sees
# already-computed values.
#
# When no active row matches, returns the generic fallback (plus a
# warning log). Notifications must NOT crash the auth flow even when
# the catalog has been mis-edited or seeds haven't run.
# ---------------------------------------------------------------------------


def _compute_placeholders(
    template_kind: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Build the dict passed to ``str.format`` from the raw dispatch payload.

    Each well-known kind contributes the placeholders documented in
    ``app/api/v3/master_data/schemas.py::_ALLOWED_PLACEHOLDERS``. Any
    extra keys in the dict are harmless — ``str.format`` ignores
    unreferenced names. Missing keys substitute as empty strings via the
    ``_SafeDict`` fallback in ``_safe_format``.
    """
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
        fe_base = (settings.FRONTEND_BASE_URL or "").rstrip("/")
        p["reset_url"] = (
            f"{fe_base}/reset-password?token={token}" if (fe_base and token) else ""
        )
    else:
        # Unknown kind: pass through the raw payload values. Templates
        # for custom kinds reference whatever keys their dispatch site
        # sends, so the renderer just forwards them.
        # Coerce known time-ish keys for convenience.
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
    """``str.format_map`` substrate that returns ``""`` for missing keys.

    Defensive: a template referencing ``{code}`` shouldn't raise
    ``KeyError`` and crash the dispatch when the dispatch site forgot
    to pass it. The placeholder validator at write time (see
    ``master_data/schemas.py``) catches the well-known kinds; this is
    the runtime safety net for custom kinds.
    """

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return ""


def _safe_format(text: Optional[str], placeholders: Dict[str, Any]) -> str:
    if not text:
        return ""
    try:
        return text.format_map(_SafeDict(placeholders))
    except (ValueError, IndexError) as e:
        # Malformed format spec (e.g. unbalanced braces). Log and fall
        # back to the raw text so dispatch still goes out — better than
        # a 500 in the auth flow.
        logger.warning(
            "notification template format failed: %s. Using raw text.", e,
        )
        return text


def _lookup_template(
    db: Session, *, template_kind: str, channel: str
) -> Optional[NotificationTemplateModel]:
    """Latest active template row for the (kind, channel) pair, or None."""
    return (
        db.query(NotificationTemplateModel)
        .filter(NotificationTemplateModel.template_kind == template_kind)
        .filter(NotificationTemplateModel.channel == channel)
        .filter(NotificationTemplateModel.active.is_(True))
        .order_by(NotificationTemplateModel.id.desc())
        .first()
    )


def _render_email(
    db: Session, template_kind: str, payload: Dict[str, Any]
) -> Tuple[str, str]:
    """Return ``(subject, html_body)`` for the email channel — DB-backed."""
    row = _lookup_template(db, template_kind=template_kind, channel=CHANNEL_EMAIL)
    if row is None:
        logger.warning(
            "No active email notification_template for kind=%r; sending fallback.",
            template_kind,
        )
        return _FALLBACK_EMAIL_SUBJECT, _FALLBACK_EMAIL_BODY
    placeholders = _compute_placeholders(template_kind, payload)
    return (
        _safe_format(row.subject, placeholders) or _FALLBACK_EMAIL_SUBJECT,
        _safe_format(row.body, placeholders),
    )


def _render_sms(
    db: Session, template_kind: str, payload: Dict[str, Any]
) -> str:
    """Return the SMS body — DB-backed."""
    row = _lookup_template(db, template_kind=template_kind, channel=CHANNEL_SMS)
    if row is None:
        logger.warning(
            "No active sms notification_template for kind=%r; sending fallback.",
            template_kind,
        )
        return _FALLBACK_SMS_BODY
    placeholders = _compute_placeholders(template_kind, payload)
    return _safe_format(row.body, placeholders)


class HttpNotificationClient(NotificationClient):
    """Production backend — talks to the PMIS-notification-service.

    Wire format (from service repo, dev branch):

      POST {NOTIFICATION_SERVICE_URL}/api/v1/notifications/email/send
      body: {"to":["x@y"], "subject":"...", "body":"...", "is_html": true}

      POST {NOTIFICATION_SERVICE_URL}/api/v1/notifications/sms/send
      body: {"to":"+91...", "message":"..."}

    The audit row is committed as ``queued`` first so we always have a
    record of what was attempted, even if the network call hangs or
    crashes. After the response we patch ``status`` to ``sent`` /
    ``failed`` and stash the provider + message_id (when returned) on
    the payload for later correlation.
    """

    def send(
        self,
        *,
        user_id: Optional[str],
        channel: str,
        recipient: str,
        template_kind: str,
        payload: Dict[str, Any],
    ) -> NotificationLogModel:
        row = NotificationLogModel(
            user_id=user_id,
            channel=channel,
            recipient=recipient,
            template_kind=template_kind,
            payload=payload,
            status="queued",
            error=None,
        )
        self.db.add(row)
        self.db.flush()
        self.db.commit()

        base_url = (settings.NOTIFICATION_SERVICE_URL or "").rstrip("/")
        if not base_url:
            # Misconfigured deploy: NOTIFICATION_CLIENT=http but no URL.
            # Don't crash the auth flow — log loud, leave the row
            # ``queued`` so ops can see the attempt, and return.
            err = (
                "NOTIFICATION_SERVICE_URL is not set; cannot dispatch "
                "via http backend."
            )
            logger.error(err)
            row.status = "failed"
            row.error = err
            self.db.flush()
            self.db.commit()
            return row

        try:
            if channel == CHANNEL_EMAIL:
                subject, body = _render_email(self.db, template_kind, payload)
                url = f"{base_url}/api/v1/notifications/email/send"
                # Resolve is_html from the active template row (doc 36).
                # Default True when the row is missing — preserves the
                # pre-doc-36 behavior for the fallback body.
                tmpl = _lookup_template(
                    self.db, template_kind=template_kind, channel=CHANNEL_EMAIL,
                )
                req_body = {
                    "to": [recipient],
                    "subject": subject,
                    "body": body,
                    "is_html": True if tmpl is None else bool(tmpl.is_html),
                }
            elif channel == CHANNEL_SMS:
                message = _render_sms(self.db, template_kind, payload)
                url = f"{base_url}/api/v1/notifications/sms/send"
                req_body = {"to": recipient, "message": message}
            else:
                err = f"Unsupported channel {channel!r}."
                logger.error(err)
                row.status = "failed"
                row.error = err
                self.db.flush()
                self.db.commit()
                return row

            with httpx.Client(
                timeout=httpx.Timeout(
                    connect=_HTTP_CONNECT_TIMEOUT,
                    read=_HTTP_READ_TIMEOUT,
                    write=_HTTP_READ_TIMEOUT,
                    pool=_HTTP_READ_TIMEOUT,
                )
            ) as client:
                resp = client.post(url, json=req_body)
        except httpx.HTTPError as e:
            err = f"notification HTTP error: {type(e).__name__}: {e}"
            logger.error(err)
            row.status = "failed"
            row.error = err
            self.db.flush()
            self.db.commit()
            return row
        except Exception as e:  # noqa: BLE001 — defensive
            err = f"notification dispatch crashed: {type(e).__name__}: {e}"
            logger.exception(err)
            row.status = "failed"
            row.error = err
            self.db.flush()
            self.db.commit()
            return row

        # Parse the response. The service returns
        #   {"success": bool, "message": str, "provider": str, "message_id": str?}
        # On non-2xx we still record what came back so investigators
        # can read the body.
        try:
            data = resp.json()
        except ValueError:
            data = {"success": False, "message": resp.text or "<no body>"}

        if 200 <= resp.status_code < 300 and data.get("success"):
            row.status = "sent"
            row.error = None
            # Stash provider + message_id on the audit payload for
            # correlation. Don't overwrite the original template
            # payload — merge under ``_dispatch``.
            new_payload = dict(payload)
            new_payload["_dispatch"] = {
                "provider": data.get("provider"),
                "message_id": data.get("message_id"),
                "service_message": data.get("message"),
            }
            row.payload = new_payload
        else:
            row.status = "failed"
            row.error = (
                f"http {resp.status_code} | "
                f"{data.get('message') or '<no message>'}"
            )
            new_payload = dict(payload)
            new_payload["_dispatch"] = {
                "http_status": resp.status_code,
                "service_response": data,
            }
            row.payload = new_payload

        self.db.flush()
        self.db.commit()
        return row


def get_notification_client(db: Session) -> NotificationClient:
    """Factory: pick the backend based on settings.

    Selection rules (first match wins):

      1. ``NOTIFICATION_CLIENT=mock`` — explicit opt-out → always mock.
         Used by the test suite via the ``mock_notification_client``
         autouse fixture so unit tests never hit a real service.
      2. ``NOTIFICATION_CLIENT=http`` — explicit opt-in → http.
      3. Empty / unset ``NOTIFICATION_CLIENT`` AND
         ``NOTIFICATION_SERVICE_URL`` is set → http (auto-detect).
         The presence of a service URL is a strong signal of intent —
         ops configured it, they want real dispatch. This is the
         common deployment path: the only env var operators have to
         set is the URL itself, which they need anyway.
      4. Otherwise → mock (safe default for fresh local dev).

    The auto-detect rule (#3) was added because ops kept setting
    ``NOTIFICATION_SERVICE_URL`` but forgetting ``NOTIFICATION_CLIENT``;
    OTPs would silently sink into ``notification_log`` instead of
    dispatching. With auto-detect, configuring the URL is enough.
    """
    backend = (settings.NOTIFICATION_CLIENT or "").strip().lower()
    has_url = bool((settings.NOTIFICATION_SERVICE_URL or "").strip())

    if backend == "mock":
        return MockNotificationClient(db)
    if backend == "http":
        return HttpNotificationClient(db)
    # No explicit setting — auto-detect by URL presence.
    if has_url:
        return HttpNotificationClient(db)
    return MockNotificationClient(db)
