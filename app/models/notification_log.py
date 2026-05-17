"""notification_log — user-svc's audit log of issued notifications.

NOT the dispatch implementation — that's notification-svc's job. This log
records WHAT user-svc has asked notification-svc to send (OTP, password
reset, etc.) plus the dispatch outcome ("queued" → "sent" / "failed").
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (
        Index("ix_nl_channel", "channel"),
        Index("ix_nl_template_kind", "template_kind"),
        Index("ix_nl_status", "status"),
        Index("ix_nl_created_at", "created_at"),
        Index("ix_nl_user_template", "user_id", "template_kind"),
        {"schema": "users"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.users.id"),
    )
    channel: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str] = mapped_column(String(255))
    template_kind: Mapped[str] = mapped_column(String(64))
    # JSONB payload — placeholders sent to notification-svc/dispatch
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[Optional[str]] = mapped_column(String(1024))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
