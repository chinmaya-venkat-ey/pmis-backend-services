"""NotificationTemplateModel — owned by pmis-notification-service after doc 38.

Pre-doc-38 this lived in user-service. Doc 38 moved ownership here so
the templates sit with the service that USES them. Schema is identical
to user-service's model — same Postgres table, same partial unique
index. The doc-38 change is code-ownership, not schema.

Renderer reads this table via TemplateService. Master endpoints
(``/api/v3/master/notification_templates/*``) write to it.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class NotificationTemplateModel(Base):
    __tablename__ = "notification_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_kind = Column(String(64), nullable=False, index=True)
    channel = Column(String(16), nullable=False, index=True)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)
    is_html = Column(Boolean, default=True, nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    description = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow, onupdate=_utcnow, nullable=False,
    )

    __table_args__ = (
        Index(
            "idx_notification_templates_kind_channel_active",
            "template_kind", "channel", "active",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationTemplateModel(id={self.id}, "
            f"kind='{self.template_kind}', channel='{self.channel}', "
            f"active={self.active}, builtin={self.is_builtin})>"
        )
