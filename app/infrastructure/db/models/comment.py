"""Comment database model.

Polymorphic — a single ``comments`` table serves milestones, activities,
tasks, and sub-tasks. ``target_kind`` discriminates; ``target_id`` is the
UUID of the target row. We don't enforce a hard FK on ``target_id``
(that's the trade-off of polymorphism); the application service layer
checks the target exists before inserting.

Indexed on ``(target_kind, target_id)`` for the dominant read pattern
("list comments for this milestone"), and on ``deleted_at`` so the
default "active rows only" filter stays cheap.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text,
)

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

    body = Column(Text, nullable=False)

    author_user_id = Column(
        Integer, nullable=False, index=True,
    )

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Soft delete (cascade-soft when parent target is soft-deleted).
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, nullable=True)

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
            f"author={self.author_user_id})>"
        )
