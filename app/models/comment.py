"""Comment SQLAlchemy model — owned by pmis-project-management.

Polymorphic via (target_kind, target_id). target_kind is one of
'milestone' | 'activity' | 'task' | 'subtask'. No DB-level FK on target_id
(targets live in different tables); service layer validates existence.

Doc-35 "send-event" model:
  - body is nullable so a row can be attachment-only.
  - attachments is a JSONB list of {url, filename, mimeType, sizeBytes, uploadedAt}.
  - Service layer enforces "body OR attachments must be present".
  - No separate attachments table.

`author_user_id` + `deleted_by` are logical FKs to `users.users.id`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        Index("idx_comments_target", "target_kind", "target_id"),
        Index("idx_comments_target_active", "target_kind", "target_id", "deleted_at"),
        Index("idx_comments_created_at", "created_at"),
        Index("ix_comments_author_user_id", "author_user_id"),
        Index("ix_comments_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )

    # Polymorphic target. No DB-level FK on target_id by design.
    target_kind: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(36))

    body: Mapped[Optional[str]] = mapped_column(Text)
    # JSONB list of {url, filename, mimeType, sizeBytes, uploadedAt}; None/[] = none.
    attachments: Mapped[Optional[list[Any]]] = mapped_column(JSONB)

    author_user_id: Mapped[str] = mapped_column(String(36))  # logical FK to users.users.id

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    # Soft-delete. body + attachments are PRESERVED on delete (master replaced
    # round-7's tombstone-with-moderation_reason design with the monolith's
    # author-or-admin soft-delete that keeps the content).
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(String(36))
