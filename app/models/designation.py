"""Designation catalog — owned by pmis-masters-management.

A simple lookup of job designations (e.g. "Consultant"). Same shape as the
other simple masters (resource_types etc.).

**Soft-delete model:** ``active=False`` (no ``deleted_at`` column — only vendors
keeps the deleted_at/deleted_by audit pattern).
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Designation(Base):
    __tablename__ = "designations"
    __table_args__ = (
        Index("ix_designations_code", "code", unique=True),
        Index("ix_designations_active", "active"),
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
