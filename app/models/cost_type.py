"""Cost-type catalog — owned by pmis-masters-management.

Drives the Project-Finance "Cost Type" dropdown on the payment screen.
Logical FK target from project.project_cost_items.cost_type_code
(cross-schema).

Code is normalized to lowercase snake (e.g. "fixed", "one_time").

**Soft-delete model:** `active=False` (NO `deleted_at` column — same
simple-deactivate model as priorities; only vendors retains the
deleted_at/deleted_by audit columns).

WARNING: Mirrored in
services/pmis-project-management/app/models/_cross_schema.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CostType(Base):
    __tablename__ = "cost_types"
    __table_args__ = (
        Index("ix_cost_types_code", "code", unique=True),
        Index("ix_cost_types_active", "active"),
        Index("idx_cost_types_active_code", "active", "code"),
        {"schema": "masters"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
