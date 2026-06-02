"""HTTP client wrapper for notification-svc dispatch.

POSTs to {NOTIFICATION_SERVICE_URL}/notification/dispatch with the
template_kind + payload + recipient. Audits every attempt in
users.notification_log (queued → sent / failed).

Has a `mock` mode (settings.notification_client=='mock') used in dev and
tests — writes the audit row but doesn't actually call out. Default.

Outbound timeout from NOTIFICATION_SERVICE_TIMEOUT_SECONDS. No retry by
design (matches monolith).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.repositories.notification_log_repository import NotificationLogRepository
from app.utilities.logger import get_logger


logger = get_logger(__name__)


class NotificationClient:
    """Dispatches notifications via notification-svc /notification/dispatch."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationLogRepository(db)

    def dispatch(
        self,
        *,
        user_id: Optional[str],
        channel: str,
        recipient: str,
        template_kind: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Send a templated notification. Returns True on success.

        Always logs to users.notification_log so the audit trail is
        complete even when dispatch fails (or runs in mock mode).
        """
        # Audit row created first as "queued" — visible even if we crash.
        log_row = self.repo.create(
            user_id=user_id,
            channel=channel,
            recipient=recipient,
            template_kind=template_kind,
            payload=payload,
            status="queued",
        )
        self.db.commit()

        client_mode = (settings.notification_client or "mock").lower()
        if client_mode == "mock":
            logger.info(
                "[MOCK NOTIFICATION] kind=%s channel=%s to=%s payload_keys=%s",
                template_kind, channel, recipient, list(payload.keys()),
            )
            self.repo.mark_sent(log_row)
            self.db.commit()
            return True

        # Real HTTP dispatch to notification-svc.
        url = f"{settings.notification_service_url.rstrip('/')}/notification/dispatch"
        body = {
            "channel": channel,
            "recipient": recipient,
            "template_kind": template_kind,
            "payload": payload,
            "user_id": user_id,
        }
        try:
            with httpx.Client(timeout=settings.notification_service_timeout_seconds) as client:
                resp = client.post(url, json=body)
            if resp.status_code >= 300:
                msg = f"{resp.status_code}: {resp.text[:500]}"
                logger.warning("Notification dispatch failed: %s", msg)
                self.repo.mark_failed(log_row, msg)
                self.db.commit()
                return False
            self.repo.mark_sent(log_row)
            self.db.commit()
            return True
        except httpx.HTTPError as exc:
            logger.error("Notification HTTP error: %s", exc)
            self.repo.mark_failed(log_row, str(exc))
            self.db.commit()
            return False
