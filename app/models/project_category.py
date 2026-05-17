"""Project category catalog — owned by pmis-masters-management (doc 37).

Backs FE project-create category dropdown. `requires_other=True` for the
"Other" sentinel row (FE then shows the free-text follow-up).

Ported from C:\\Programming\\PMIS\\PMIS-OpenProject\\app\\infrastructure\\db\\models\\project_category.py:26
with SQLAlchemy 2.0 patterns.

WARNING: Mirrored read-only from services/pmis-project-management
(project.projects.category FK target).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectCategory(Base):
    __tablename__ = "project_categories"
    __table_args__ = (
        Index("ix_project_categories_code", "code", unique=True),
        Index("ix_project_categories_active", "active"),
        {"schema": "masters"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_other: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(1024))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
