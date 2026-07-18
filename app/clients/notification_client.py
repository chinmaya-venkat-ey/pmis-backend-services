"""HTTP client for pmis-notification-service — used by the
'activity completed → evaluate SLAs' workflow.

When an activity completes, contract-management auto-evaluates every
SLA on it. For SLAs whose observation can be derived from the activity's
own dates (``fixed_escalation``), the evaluator runs immediately. For
SLAs that need a recorded observation (``point_accumulation`` /
``band_accumulation`` / ``wac``), we email the project + activity
owners so they know to record the value.

Templates referenced here should exist in pmis-notification-service's
template catalog. If a template is missing, notification-svc logs a
"template missing" error but the dispatch call still returns 2xx — the
caller doesn't need to handle that case explicitly.

Modes:
  * ``real``  — POSTs to the configured notification service URL
  * ``mock``  — logs the call only (safe default for local dev)

Failures are LOGGED, not raised. The activity-completion endpoint MUST
NOT fail because the notification service is flaky.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# Template kinds used by the SLA-completion workflow.
TEMPLATE_SLA_MANUAL_REVIEW = "sla_manual_review_needed"
TEMPLATE_SLA_AUTO_EVALUATED = "sla_auto_evaluated"


class NotificationClient:
    """Thin httpx wrapper around notification-svc /notification/dispatch.

    Stateless — construct per request. Failures logged, not raised.
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
        # Safety net: even when the config asked for "real", we can't
        # POST anywhere without a URL. Downgrade to mock so the caller
        # gets a cleanly-logged send instead of an httpx exception:
        #     "Request URL is missing an 'http://' or 'https://' protocol"
        # (Live 2026-07-18 — the VM container has NOTIFICATION_CLIENT=real
        # but NOTIFICATION_SERVICE_URL unset; without this guard every
        # dispatch would fail visibly in container logs.)
        if self.mode == "real" and not self.base_url:
            logger.warning(
                "NotificationClient: configured mode='real' but no "
                "notification_service_url set — forcing mock mode."
            )
            self.mode = "mock"

    def dispatch(
        self,
        *,
        template_kind: str,
        recipient: str,
        payload: Dict[str, Any],
        user_id: Optional[str] = None,
        channel: str = "email",
    ) -> bool:
        """POST to /notification/dispatch. Returns True on 2xx."""
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
                "Notification dispatch failed for %s: %s", template_kind, exc,
            )
            return False
        if resp.status_code >= 400:
            logger.warning(
                "Notification dispatch non-2xx for %s: %s %s",
                template_kind, resp.status_code, resp.text[:300],
            )
            return False
        return True

    def send_email(
        self,
        *,
        to: Iterable[str],
        subject: str,
        body: str,
        is_html: bool = False,
    ) -> bool:
        """Direct email — bypass the template system. Used when the
        SLA-completion flow wants to send a subject/body it composed
        itself rather than relying on a template that may not exist.
        Returns True on 2xx."""
        recipients = [t for t in to if t]
        if not recipients:
            return False
        if self.mode == "mock":
            logger.info(
                "[MOCK EMAIL] to=%s subject=%r len(body)=%d",
                recipients, subject, len(body),
            )
            return True
        url = f"{self.base_url}/notification/email/send"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json={
                    "to": recipients,
                    "subject": subject,
                    "body": body,
                    "is_html": is_html,
                })
        except httpx.HTTPError as exc:
            logger.warning("Email send failed to %s: %s", recipients, exc)
            return False
        if resp.status_code >= 400:
            logger.warning(
                "Email send non-2xx for %s: %s %s",
                recipients, resp.status_code, resp.text[:300],
            )
            return False
        return True