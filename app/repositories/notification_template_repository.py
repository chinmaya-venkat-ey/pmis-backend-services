"""Data access for the notification_templates catalog (moved here per Q3).

notification-svc READS this table cross-schema; masters-svc OWNS it.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification_template import NotificationTemplate


class NotificationTemplateRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, template_id: int) -> Optional[NotificationTemplate]:
        return self.db.get(NotificationTemplate, template_id)

    def find_active(
        self,
        *,
        template_kind: str,
        channel: str,
    ) -> Optional[NotificationTemplate]:
        """Find the most recent active template for (template_kind, channel)."""
        stmt = (
            select(NotificationTemplate)
            .where(NotificationTemplate.template_kind == template_kind)
            .where(NotificationTemplate.channel == channel)
            .where(NotificationTemplate.active.is_(True))
            .order_by(NotificationTemplate.id.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def find_by_kind_and_channel_any(
        self,
        *,
        template_kind: str,
        channel: str,
    ) -> Optional[NotificationTemplate]:
        """Find any row (active or not) — used to detect clashes on create."""
        stmt = (
            select(NotificationTemplate)
            .where(NotificationTemplate.template_kind == template_kind)
            .where(NotificationTemplate.channel == channel)
            .order_by(NotificationTemplate.id.desc())
        )
        return self.db.execute(stmt).scalars().first()

    def list_(self, *, include_inactive: bool = False) -> List[NotificationTemplate]:
        stmt = select(NotificationTemplate)
        if not include_inactive:
            stmt = stmt.where(NotificationTemplate.active.is_(True))
        stmt = stmt.order_by(
            NotificationTemplate.template_kind.asc(),
            NotificationTemplate.channel.asc(),
            NotificationTemplate.id.asc(),
        )
        return list(self.db.execute(stmt).scalars().all())

    def create(self, **kwargs) -> NotificationTemplate:
        row = NotificationTemplate(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: NotificationTemplate, **kwargs) -> NotificationTemplate:
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        self.db.flush()
        return row

    def deactivate(self, row: NotificationTemplate) -> NotificationTemplate:
        row.active = False
        self.db.flush()
        return row

    def reactivate(self, row: NotificationTemplate) -> NotificationTemplate:
        row.active = True
        self.db.flush()
        return row
