"""Permission SQLAlchemy model — owned by pmis-user-management.

The `code` column (e.g. "users:create", "divisions:read") is the PK.
Seeded by the bootstrap data-migration with ALL permission codes used
across all four services.

WARNING: Mirrored in services/pmis-masters-management/app/models/_cross_schema.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = ({"schema": "users"},)

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
