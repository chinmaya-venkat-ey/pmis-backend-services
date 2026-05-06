"""Comment database model.

Polymorphic — a single ``comments`` table serves milestones, activities,
tasks, and sub-tasks. ``target_kind`` discriminates; ``target_id`` is the
UUID of the target row. We don't enforce a hard FK on ``target_id``
(that's the trade-off of polymorphism); the application service layer
checks the target exists before inserting.

Doc 35 (this revision) — "send-event" model:
  - A row represents one comment-or-attachment "send event" (like an
    email). It can carry a body, an attachment list, or both.
  - ``body`` is nullable. A row with ``body NULL`` and a populated
    ``attachments`` array represents an attachment-only send.
  - ``attachments`` is a JSON column (JSONB on Postgres) holding a
    list of objects: ``{url, filename, mimeType, sizeBytes, uploadedAt}``.
    The URL points at the external file server (or a fallback path
    served by the BE in dev) — clients fetch bytes directly from the
    URL and never go through a BE-streaming download.
  - The separate ``attachments`` table is gone.

Indexed on ``(target_kind, target_id)`` for the dominant read pattern
("list comments for this milestone"), and on ``deleted_at`` so the
default "active rows only" filter stays cheap.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
)

from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class CommentModel(Base):
    __tablename__ = "comments"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # Polymorphic target. target_kind is one of the TARGET_KINDS enum
    # values from app.domain.comments. target_id is the UUID of the
    # M/A/T/S row. No DB-level FK because target lives in a different
    # table per kind.
    target_kind = Column(String(20), nullable=False)
    target_id = Column(String(36), nullable=False)

    # Doc 35: body is now nullable so a row can be attachment-only.
    # Service layer enforces "body OR attachments must be present".
    body = Column(Text, nullable=True)

    # Doc 35: attachments live on the comment row itself as a JSON list.
    # Each entry: ``{url, filename, mimeType, sizeBytes, uploadedAt}``.
    # The URL is the external file server's address (with ip:port) where
    # the FE fetches bytes directly. ``None``/``[]`` ⇒ no attachments.
    attachments = Column(JSON, nullable=True)

    # Doc 26: users.id flipped to UUID String(36).
    author_user_id = Column(
        String(36), ForeignKey("users.id"), nullable=False, index=True,
    )

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    updated_at = Column(UtcDateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Soft delete (cascade-soft when parent target is soft-deleted).
    deleted_at = Column(UtcDateTime, nullable=True, index=True)
    deleted_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("idx_comments_target", "target_kind", "target_id"),
        Index("idx_comments_target_active",
              "target_kind", "target_id", "deleted_at"),
        Index("idx_comments_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<CommentModel(id='{self.id}', "
            f"target={self.target_kind}/{self.target_id}, "
            f"author={self.author_user_id}, "
            f"attachments={len(self.attachments or [])})>"
        )
