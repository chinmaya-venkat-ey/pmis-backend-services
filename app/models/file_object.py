"""FileObject ORM model — owned by the files schema.

One row per uploaded file. The S3 object key is the canonical storage
reference; the row also carries display metadata (original_filename,
mime_type, size) and contextual metadata (folder, entity_type, entity_id)
for search and scoping.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.utilities.timezones import utcnow


class FileObject(Base):
    """Stores metadata for every uploaded file in the files schema."""
    __tablename__ = "file_objects"
    __table_args__ = (
        Index("idx_file_objects_folder", "folder"),
        Index("idx_file_objects_entity", "entity_type", "entity_id"),
        Index("idx_file_objects_uploaded_by", "uploaded_by"),
        Index("idx_file_objects_created_at", "created_at"),
        Index("idx_file_objects_deleted_at", "deleted_at"),
        {"schema": "files"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Logical folder — caller-provided grouping (e.g. "project-attachments",
    # "profile-photos", "milestone-attachments").
    folder: Mapped[str] = mapped_column(String(255), nullable=False)

    # Optional entity scope — used for filtered search.
    entity_type: Mapped[Optional[str]] = mapped_column(String(100))
    entity_id: Mapped[Optional[str]] = mapped_column(String(36))

    # Display / user-visible filename (original name the user uploaded).
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)

    # S3 storage references.
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    s3_bucket: Mapped[str] = mapped_column(String(255), nullable=False)

    # Content metadata.
    mime_type: Mapped[Optional[str]] = mapped_column(String(255))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))

    # Public URL if bucket/CDN is public. NULL = use pre-signed URLs.
    public_url: Mapped[Optional[str]] = mapped_column(Text)

    # Arbitrary caller-provided metadata (tags, labels, custom fields).
    extra_metadata: Mapped[Optional[Any]] = mapped_column(JSONB)

    # Who uploaded the file.
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(36))

    # Soft-delete.
    deleted_at: Mapped[Optional[datetime]] = mapped_column()
    deleted_by: Mapped[Optional[str]] = mapped_column(String(36))

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
