"""Notification template catalog — owned by pmis-masters-management.

Per Q3, ownership moved from notification-svc to masters-svc. Templates
are configurable reference data; admins manage them via
/masters/notification-templates/{create,update,delete,restore}.

notification-svc READS this table cross-schema for dispatch + daily-digest
template render (see services/pmis-notification-management/app/models/_cross_schema.py:NotificationTemplate).

Ported from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\db\\models\\notification_template.py:22
with SQLAlchemy 2.0 patterns.

WARNING: This model is MIRRORED in:
  - services/pmis-notification-management/app/models/_cross_schema.py (NotificationTemplate)
Column changes here MUST be replicated.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    __table_args__ = (
        Index("ix_notification_templates_template_kind", "template_kind"),
        Index("ix_notification_templates_channel", "channel"),
        Index("ix_notification_templates_active", "active"),
        Index(
            "idx_notification_templates_kind_channel_active",
            "template_kind", "channel", "active",
        ),
        {"schema": "masters"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_kind: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16))
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    is_html: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(1024))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
