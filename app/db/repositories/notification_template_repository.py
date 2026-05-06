"""Notification template repository (doc 38)."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from ..models.notification_template import NotificationTemplateModel


class NotificationTemplateRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_(self, include_inactive: bool = False) -> List[NotificationTemplateModel]:
        q = self.db.query(NotificationTemplateModel)
        if not include_inactive:
            q = q.filter(NotificationTemplateModel.active.is_(True))
        return q.order_by(
            NotificationTemplateModel.template_kind.asc(),
            NotificationTemplateModel.channel.asc(),
            NotificationTemplateModel.id.asc(),
        ).all()

    def get_by_id(self, template_id: int) -> Optional[NotificationTemplateModel]:
        return self.db.get(NotificationTemplateModel, template_id)

    def find_active(self, *, template_kind: str, channel: str) -> Optional[NotificationTemplateModel]:
        return (
            self.db.query(NotificationTemplateModel)
            .filter(NotificationTemplateModel.template_kind == template_kind)
            .filter(NotificationTemplateModel.channel == channel)
            .filter(NotificationTemplateModel.active.is_(True))
            .order_by(NotificationTemplateModel.id.desc())
            .first()
        )

    def create(self, **kwargs) -> NotificationTemplateModel:
        row = NotificationTemplateModel(**kwargs)
        self.db.add(row)
        self.db.flush()
        return row

    def commit(self) -> None:
        self.db.commit()
