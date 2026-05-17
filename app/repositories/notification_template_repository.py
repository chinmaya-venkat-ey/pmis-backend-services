"""Read-only repository for masters.notification_templates.

Per Q3, the notification_templates table is OWNED by pmis-masters-management.
This repository reads from the cross-schema mirror declared in
app/models/_cross_schema.py.

Writes to notification_templates happen exclusively in pmis-masters-management
via /masters/notification-templates/{create,update,delete,restore}.

Ported from
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\db\\repositories\\notification_template_repository.py:1-46
with the following changes:
  - Reads from masters.notification_templates (cross-schema) not the local schema.
  - Uses SQLAlchemy 2.0 `select()` API per PLAN.md §2.1.
  - Drops write methods (create / commit) — those belong to masters-svc.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import NotificationTemplate


class NotificationTemplateRepository:
    """READ-ONLY repo against the cross-schema mirror of masters.notification_templates."""

    def __init__(self, db: Session):
        self.db = db

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

    def get_by_id(self, template_id: int) -> Optional[NotificationTemplate]:
        return self.db.get(NotificationTemplate, template_id)

    def list_active(self) -> List[NotificationTemplate]:
        stmt = (
            select(NotificationTemplate)
            .where(NotificationTemplate.active.is_(True))
            .order_by(
                NotificationTemplate.template_kind.asc(),
                NotificationTemplate.channel.asc(),
                NotificationTemplate.id.asc(),
            )
        )
        return list(self.db.execute(stmt).scalars().all())
