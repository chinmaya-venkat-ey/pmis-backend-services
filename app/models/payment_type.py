"""Payment-type catalog — owned by pmis-masters-management.

Drives the milestone "Payment Type" dropdown. Logical FK target from
project.milestones.payment_type (cross-schema).

Code is normalized to lowercase snake (e.g. "partial_payment",
"complete_payment").

**Soft-delete model:** `active=False` (NO `deleted_at` column — same
simple-deactivate model as cost_types / priorities).

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


class PaymentType(Base):
    __tablename__ = "payment_types"
    __table_args__ = (
        Index("ix_payment_types_code", "code", unique=True),
        Index("ix_payment_types_active", "active"),
        Index("idx_payment_types_active_code", "active", "code"),
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
