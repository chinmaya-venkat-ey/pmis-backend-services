"""Business logic for the notification_templates catalog (moved here per Q3).

notification-svc reads this catalog cross-schema; masters-svc owns writes.

Enforces:
  - Unique (template_kind, channel) on create
  - Built-in rows can't be deleted
  - "Delete" = active=False (no deleted_at column on this catalog)
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.errors import (
    CatalogEntryConflictError,
    CatalogEntryNotFoundError,
)
from app.models.notification_template import NotificationTemplate
from app.repositories.notification_template_repository import (
    NotificationTemplateRepository,
)
from app.schemas.notification_template import (
    NotificationTemplateCreateRequest,
    NotificationTemplateUpdateRequest,
)


class NotificationTemplateService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationTemplateRepository(db)

    def list_(self, *, include_inactive: bool = False) -> List[NotificationTemplate]:
        return self.repo.list_(include_inactive=include_inactive)

    def get_by_id(self, template_id: int) -> NotificationTemplate:
        row = self.repo.get_by_id(template_id)
        if row is None:
            raise CatalogEntryNotFoundError(
                f"NotificationTemplate {template_id!r} not found"
            )
        return row

    def create(
        self, payload: NotificationTemplateCreateRequest
    ) -> NotificationTemplate:
        existing = self.repo.find_by_kind_and_channel_any(
            template_kind=payload.template_kind, channel=payload.channel
        )
        if existing is not None and existing.active:
            raise CatalogEntryConflictError(
                f"NotificationTemplate ({payload.template_kind!r}, {payload.channel!r}) "
                "already exists and is active",
                details={
                    "template_kind": payload.template_kind,
                    "channel": payload.channel,
                },
            )
        row = self.repo.create(
            template_kind=payload.template_kind,
            channel=payload.channel,
            subject=payload.subject,
            body=payload.body,
            is_html=payload.is_html,
            is_builtin=False,
            active=True,
            description=payload.description,
        )
        self.db.commit()
        return row

    def update(
        self, template_id: int, payload: NotificationTemplateUpdateRequest
    ) -> NotificationTemplate:
        row = self.get_by_id(template_id)
        self.repo.update(row, **payload.model_dump(exclude_unset=True))
        self.db.commit()
        return row

    def delete(self, template_id: int) -> NotificationTemplate:
        row = self.get_by_id(template_id)
        # is_builtin is informational only — all templates are deletable.
        self.repo.deactivate(row)
        self.db.commit()
        return row

    def restore(self, template_id: int) -> NotificationTemplate:
        row = self.get_by_id(template_id)
        # If another row is active for the same (kind, channel), reject restore.
        active = self.repo.find_active(
            template_kind=row.template_kind, channel=row.channel
        )
        if active is not None and active.id != row.id:
            raise CatalogEntryConflictError(
                f"Another active template exists for ({row.template_kind!r}, {row.channel!r}); "
                "deactivate it before restoring this one",
                details={"conflicting_id": active.id},
            )
        self.repo.reactivate(row)
        self.db.commit()
        return row
