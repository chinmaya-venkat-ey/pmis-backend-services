"""Activity type catalog — owned by pmis-masters-management (doc 37).

FK target from project.activities.type (nullable post-doc-38).

Ported from C:\\Programming\\PMIS\\PMIS-OpenProject\\app\\infrastructure\\db\\models\\activity_type.py:26.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActivityType(Base):
    __tablename__ = "activity_types"
    __table_args__ = (
        Index("ix_activity_types_code", "code", unique=True),
        Index("ix_activity_types_active", "active"),
        {"schema": "masters"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
