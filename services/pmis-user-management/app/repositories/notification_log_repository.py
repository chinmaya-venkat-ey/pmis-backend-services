"""NotificationLogRepository — user-svc's audit trail for issued notifications.

Each row records WHAT user-svc asked notification-svc to dispatch, along with
the outcome (queued → sent / failed).
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.notification_log import NotificationLog


class NotificationLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: Optional[str],
        channel: str,
        recipient: str,
        template_kind: str,
        payload: dict[str, Any],
        status: str = "queued",
    ) -> NotificationLog:
        row = NotificationLog(
            user_id=user_id,
            channel=channel,
            recipient=recipient,
            template_kind=template_kind,
            payload=payload,
            status=status,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def mark_sent(self, row: NotificationLog) -> NotificationLog:
        row.status = "sent"
        row.error = None
        self.db.flush()
        return row

    def mark_failed(self, row: NotificationLog, error: str) -> NotificationLog:
        row.status = "failed"
        row.error = error[:1000]
        self.db.flush()
        return row
