"""FileAuditLog ORM model — immutable audit trail for all file operations.

Every upload, download (URL generation), delete, restore, and search
that touches a file produces one row here. The table is append-only;
rows are never updated or deleted.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.utilities.timezones import utcnow


class FileAuditLog(Base):
    """Append-only audit log for all file operations."""
    __tablename__ = "file_audit_logs"
    __table_args__ = (
        Index("idx_file_audit_logs_file_id", "file_id"),
        Index("idx_file_audit_logs_actor", "actor_user_id"),
        Index("idx_file_audit_logs_action", "action"),
        Index("idx_file_audit_logs_entity", "entity_type", "entity_id"),
        Index("idx_file_audit_logs_created_at", "created_at"),
        {"schema": "files"},
    )

    # Serial primary key — BigInteger matches PostgreSQL BIGSERIAL.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Target file — nullable for bulk/folder-level operations.
    file_id: Mapped[Optional[str]] = mapped_column(String(36))

    # What happened.
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # Action values: upload | download | delete | restore | list | search

    # Who did it.
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36))

    # Contextual fields (denormalized for query efficiency — no JOIN needed).
    folder: Mapped[Optional[str]] = mapped_column(String(255))
    entity_type: Mapped[Optional[str]] = mapped_column(String(100))
    entity_id: Mapped[Optional[str]] = mapped_column(String(36))

    # Original filename for display in audit reports (duplicated from
    # file_objects to survive after soft-delete).
    original_filename: Mapped[Optional[str]] = mapped_column(String(500))

    # Action-specific context (e.g. search filters, delete reason).
    extra_metadata: Mapped[Optional[Any]] = mapped_column(JSONB)

    # Network context.
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
