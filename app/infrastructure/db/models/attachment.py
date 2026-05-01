"""Attachment database model.

Each row is metadata for a file stored on disk (the bytes live under
``settings.ATTACHMENTS_STORAGE_BASE_PATH`` at the path given by
``storage_key``).

An attachment is EITHER bound to a comment (``comment_id`` set) OR is a
standalone node attachment (``target_kind`` + ``target_id`` set, no
comment). The application layer enforces this invariant — we don't add
a CHECK constraint here so the schema stays portable to SQLite (used
in tests).

``storage_key`` is unique — we never reuse a key, so deleting a file
and uploading a new one produces a fresh key.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Index, Integer, String,
)

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class AttachmentModel(Base):
    __tablename__ = "attachments"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # When set, this attachment belongs to a comment. When NULL, the
    # attachment is standalone on a node and target_kind/target_id are set.
    comment_id = Column(
        String(36), ForeignKey("comments.id"), nullable=True, index=True,
    )

    # Standalone target (only used when comment_id IS NULL).
    target_kind = Column(String(20), nullable=True)
    target_id = Column(String(36), nullable=True)

    original_filename = Column(String(500), nullable=False)
    storage_key = Column(String(500), nullable=False, unique=True)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)

    uploaded_by_user_id = Column(
        Integer, nullable=False, index=True,
    )
    uploaded_at = Column(DateTime, default=_utcnow, nullable=False)

    # Soft delete (the storage cleanup cron purges bytes after retention).
    deleted_at = Column(DateTime, nullable=True, index=True)
    deleted_by = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_attachments_target", "target_kind", "target_id"),
        Index("idx_attachments_target_active",
              "target_kind", "target_id", "deleted_at"),
        Index("idx_attachments_uploaded_at", "uploaded_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AttachmentModel(id='{self.id}', "
            f"comment_id={self.comment_id}, "
            f"target={self.target_kind}/{self.target_id}, "
            f"file='{self.original_filename}', size={self.size_bytes})>"
        )
