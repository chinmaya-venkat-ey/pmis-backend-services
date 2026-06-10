"""SlaAttachment model — image attached to an SLA template.

Bytes live in pmis-file-store; this row only carries the handle and a
cached download URL. See migration 0017_sla_attachments for the table
shape and rationale.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaAttachment(Base):
    __tablename__ = "sla_attachments"
    __table_args__ = (
        Index("ix_sla_attachments_file_id", "file_id"),
        # The partial "live rows only" index is created in the migration —
        # SQLAlchemy doesn't model partial indexes cleanly in __table_args__
        # so we keep it out of here.
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "contract.sla_definitions.id",
            ondelete="CASCADE",
            name="fk_sla_attachments_sla_id",
        ),
        nullable=False,
    )
    # Canonical handle from pmis-file-store. Used for refresh-url + delete.
    file_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Cached download URL. Returned as-is on list; refreshed via the
    # POST /attachments/{id}/refresh-url endpoint when it expires.
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255))
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    caption: Mapped[Optional[str]] = mapped_column(String(500))
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(36))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
    # Soft-delete: filtered out by the live partial index; the row sticks
    # around for audit. Hard-delete is reserved for the cascade triggered
    # by SLA hard-deletion (which we avoid in practice).
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
