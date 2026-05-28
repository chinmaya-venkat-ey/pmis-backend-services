"""HTTP client for dispatching activity-workflow notifications to
PMIS-notification-service.

Mirrors the user-svc pattern (``PMIS-user-management/app/services/
notification_client.py``) but lives in project-management because the
activity workflow events originate here.

POSTs to ``{NOTIFICATION_SERVICE_URL}/notification/dispatch`` with
``{channel, recipient, template_kind, payload, user_id}``. In mock mode
(``NOTIFICATION_CLIENT=mock``, or no URL configured) the call is logged
without an outbound request — useful in dev / tests where the
notification service isn't running.

Note: project-management does NOT maintain a local
``notification_log`` table (user-svc owns that audit trail). The
notification service itself records every dispatch internally; PMIS
side just logs a single line via the standard logger so failures are
visible in container logs without inventing a new table.

Templates referenced by the approval-inbox flow:
  * ``activity_submitted_to_division`` — fires on SUBMIT (and re-SUBMIT
    after UPDATE). Recipients: users in each consent division.
  * ``activity_approved_by_division``  — fires when the
    concerned-division stage clears. Recipient: users in the owner
    division.
  * ``activity_completed``             — fires on owner APPROVE.
    Recipient: the activity vendor's contact email.
  * ``activity_rejected``              — fires on REJECT at either
    stage. Recipient: the activity vendor's contact email.

If a template doesn't exist on notification-service yet, the dispatch
call still goes out — notification-svc will log a "template missing"
error but won't crash the caller. The approval transition succeeds
regardless of notification outcome (best-effort, no retry).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# Template kinds — keep here so the service layer doesn't reference
# string literals directly.
TEMPLATE_SUBMITTED_TO_DIVISION = "activity_submitted_to_division"
TEMPLATE_APPROVED_BY_DIVISION = "activity_approved_by_division"
TEMPLATE_COMPLETED = "activity_completed"
TEMPLATE_REJECTED = "activity_rejected"


class NotificationClient:
    """Thin httpx wrapper around notification-svc /notification/dispatch.

    Stateless beyond the configured URL/timeout/mode — safe to construct
    per request. Failures are LOGGED, not raised — a flaky notification
    backend must never block an approval transition. Callers may
    ignore the boolean return when best-effort is sufficient.
    """

    def __init__(self) -> None:
        self.base_url = (
            getattr(settings, "notification_service_url", None) or ""
        ).rstrip("/")
        self.timeout = float(
            getattr(settings, "notification_service_timeout_seconds", 5.0)
        )
        configured_mode = (
            getattr(settings, "notification_client", None) or ""
        ).lower()
        if configured_mode in ("mock", "real"):
            self.mode = configured_mode
        else:
            self.mode = "real" if self.base_url else "mock"

    def dispatch(
        self,
        *,
        user_id: Optional[str],
        channel: str,
        recipient: str,
        template_kind: str,
        payload: Dict[str, Any],
    ) -> bool:
        if not recipient:
            logger.debug(
                "[NOTIFY] skip %s — no recipient", template_kind,
            )
            return False
        if self.mode == "mock":
            logger.info(
                "[MOCK NOTIFY] kind=%s channel=%s to=%s payload_keys=%s",
                template_kind, channel, recipient, list(payload.keys()),
            )
            return True
        url = f"{self.base_url}/notification/dispatch"
        body = {
            "channel": channel,
            "recipient": recipient,
            "template_kind": template_kind,
            "payload": payload,
            "user_id": user_id,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=body)
        except httpx.HTTPError as exc:
            logger.warning(
                "Notification dispatch failed for %s: %s",
                template_kind, exc,
            )
            return False
        if resp.status_code >= 400:
            logger.warning(
                "Notification dispatch non-2xx for %s: %s %s",
                template_kind, resp.status_code, resp.text[:300],
            )
            return False
        return True

    def dispatch_many(
        self,
        recipients: Iterable[str],
        *,
        template_kind: str,
        payload: Dict[str, Any],
        channel: str = "email",
    ) -> int:
        """Dispatch the same template to multiple recipients.
        Returns the count of successful sends. Failures are logged
        individually — partial success is fine."""
        sent = 0
        for r in recipients:
            if self.dispatch(
                user_id=None, channel=channel, recipient=r,
                template_kind=template_kind, payload=payload,
            ):
                sent += 1
        return sent
