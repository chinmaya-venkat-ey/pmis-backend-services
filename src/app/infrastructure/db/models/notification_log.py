"""Notification log (doc 33 change 3).

Every notification dispatched by the system is recorded here regardless
of which backend (`mock` or `http`) handled it. The mock backend uses
this table as its terminal sink (no real send happens); the http
backend writes a row before the call so failures are visible. The
column shape is intentionally small — payload is JSON so the schema
doesn't need to change for new notification kinds.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Index, Integer, JSON, String

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class NotificationLogModel(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # The user this notification targets (nullable so deleted users
    # still leave a clean trail — the FK has ON DELETE SET NULL effectively).
    user_id = Column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    # ``email`` or ``sms``.
    channel = Column(String(16), nullable=False, index=True)

    # The actual recipient (email address or phone number) at the time
    # of dispatch. Captured here so audits stay correct even if the user
    # later changes their contact details.
    recipient = Column(String(320), nullable=False)

    # Template kind: ``otp_login`` / ``password_reset_link`` /
    # ``password_reset_otp`` / ... — additive, no enum.
    template_kind = Column(String(64), nullable=False, index=True)

    # Free-form JSON payload — never stores secrets (codes are stored
    # hashed in their own tables; the payload mentions the kind only).
    payload = Column(JSON, nullable=True)

    # Send result. ``queued`` (mock) / ``sent`` / ``failed``. The
    # http backend writes ``queued`` pre-call and updates after.
    status = Column(String(16), nullable=False, default="queued", index=True)

    # If the backend reported an error, the message lands here.
    error = Column(String(500), nullable=True)

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_notification_log_user_id_kind", "user_id", "template_kind"),
        Index("idx_notification_log_created_at", "created_at"),
    )
