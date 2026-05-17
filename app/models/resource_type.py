"""Resource type catalog — owned by pmis-masters-management.

FK target from project.activity_resources.type_of_resource_id.

**Soft-delete model:** `active=False` (NO `deleted_at` column — per user
direction, only vendors keeps the deleted_at/deleted_by audit pattern).

WARNING: Mirrored in services/pmis-project-management/app/models/_cross_schema.py.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ResourceType(Base):
    __tablename__ = "resource_types"
    __table_args__ = (
        Index("ix_resource_types_code", "code", unique=True),
        Index("ix_resource_types_active", "active"),
        {"schema": "masters"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
