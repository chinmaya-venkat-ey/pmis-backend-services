"""Division catalog — owned by pmis-masters-management.

Backs project-owner picker (project-creation form) and user-form division
dropdown. Three rows seeded by alembic bootstrap migration: tmd1 / tmd2 / others.
Doc 36 made email + phone NOT NULL.

Ported from C:\\Programming\\PMIS\\PMIS-OpenProject\\app\\infrastructure\\db\\models\\division.py:41
with SQLAlchemy 2.0 patterns (Mapped[T] / mapped_column) per PLAN.md §2.1.

WARNING: This model is MIRRORED in:
  - services/pmis-user-management/app/models/_cross_schema.py (DivisionModel)
  - services/pmis-project-management/app/models/_cross_schema.py (Division)
Column changes here MUST be replicated. Q24 CI drift test enforces.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Division(Base):
    __tablename__ = "divisions"
    __table_args__ = (
        Index("ix_divisions_code", "code", unique=True),
        Index("ix_divisions_active", "active"),
        Index("idx_divisions_code_active", "code", "active"),
        {"schema": "masters"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_other: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Doc 36: mandatory contact details.
    email: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
