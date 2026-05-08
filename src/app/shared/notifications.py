"""Notification client (doc 38 phase 2).

Two backends behind one ``NotificationClient`` interface:

- ``MockNotificationClient`` — writes to ``notification_log`` and
  returns. The terminal sink during dev/tests; never makes a real HTTP
  call. Inspecting the table reveals every notification that would
  have been sent, with the recipient, channel, and template kind.

- ``HttpNotificationClient`` — POSTs to the live notification
  microservice (https://github.com/EY-DIGIT/PMIS-notification-service).
  Calls a single endpoint:
      POST {NOTIFICATION_SERVICE_URL}/api/v1/notifications/dispatch
  with ``{channel, recipient, template_kind, payload, user_id}``. The
  notification-service owns template lookup + rendering — user-mgmt
  passes the dispatch intent through and records the audit row. The
  audit row is written as ``queued`` first so we always have a record
  of what was attempted, then patched to ``sent``/``failed`` once the
  call returns.

Selection happens via the ``NOTIFICATION_CLIENT`` env var:
  - ``mock`` (default in dev/tests)
  - ``http`` (production / staging — needs ``NOTIFICATION_SERVICE_URL``)

Construct via the factory ``get_notification_client(db)`` — it picks
the backend based on settings and hands back an instance bound to the
provided session.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.orm import Session

from ..core.config import settings
from ..infrastructure.db.models.notification_log import NotificationLogModel


logger = logging.getLogger(__name__)


# Channel constants.
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"

# Template kinds — well-known; auth flows use these. Custom kinds are
# fine too; notification-service falls back to a generic body when no
# active row matches.
TEMPLATE_OTP_LOGIN = "otp_login"
TEMPLATE_PASSWORD_RESET_LINK = "password_reset_link"
TEMPLATE_PASSWORD_RESET_OTP = "password_reset_otp"


# HTTP timeouts. Short connect timeout so a stuck DNS / unreachable host
# fails fast and doesn't block the auth flow; longer read timeout for
# legitimate slow email-provider hops (SendGrid / SMTP relays).
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

        Returns the persisted row so callers can correlate. Committed
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
            status="sent",
            error=None,
        )
        self.db.add(row)
        self.db.flush()
        self.db.commit()
        return row


class HttpNotificationClient(NotificationClient):
    """Production backend — talks to PMIS-notification-service.

    Single round trip: POST {url}/api/v1/notifications/dispatch with
    ``{channel, recipient, template_kind, payload, user_id}``. The
    service does the template lookup, placeholder substitution, and
    provider call.
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

        if channel not in (CHANNEL_EMAIL, CHANNEL_SMS):
            err = f"Unsupported channel {channel!r}."
            logger.error(err)
            row.status = "failed"
            row.error = err
            self.db.flush()
            self.db.commit()
            return row

        url = f"{base_url}/api/v1/notifications/dispatch"
        req_body = {
            "channel": channel,
            "recipient": recipient,
            "template_kind": template_kind,
            "payload": payload,
            "user_id": user_id,
        }

        try:
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

        try:
            data = resp.json()
        except ValueError:
            data = {"success": False, "message": resp.text or "<no body>"}

        if 200 <= resp.status_code < 300 and data.get("success"):
            row.status = "sent"
            row.error = None
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
                f"{data.get('message') or data.get('detail') or '<no message>'}"
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
    """Pick the backend based on settings.

    Selection rules (first match wins):
      1. ``NOTIFICATION_CLIENT=mock`` — explicit opt-out → mock.
      2. ``NOTIFICATION_CLIENT=http`` — explicit opt-in → http.
      3. Empty / unset AND ``NOTIFICATION_SERVICE_URL`` is set → http
         (auto-detect; configuring the URL is a strong signal of intent).
      4. Otherwise → mock (safe default for fresh local dev).
    """
    backend = (settings.NOTIFICATION_CLIENT or "").strip().lower()
    has_url = bool((settings.NOTIFICATION_SERVICE_URL or "").strip())

    if backend == "mock":
        return MockNotificationClient(db)
    if backend == "http":
        return HttpNotificationClient(db)
    if has_url:
        return HttpNotificationClient(db)
    return MockNotificationClient(db)
