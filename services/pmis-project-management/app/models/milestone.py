"""Milestone SQLAlchemy model — owned by pmis-project-management.

Per-project position is unique among LIVE rows (partial unique index where
`deleted_at IS NULL`). Drives the M{n} display label.

`priority` is a logical FK to `masters.priorities.code` (cross-schema).
`status` is a logical FK to `masters.milestone_statuses.code`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        Index("idx_milestones_project_live", "project_id", "deleted_at"),
        Index("idx_milestones_project_position", "project_id", "position"),
        Index(
            "uq_milestones_project_position_live",
            "project_id", "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_milestones_status", "status"),
        Index("ix_milestones_priority", "priority"),
        Index("ix_milestones_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.projects.id"),
    )

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="not_completed")
    priority: Mapped[Optional[str]] = mapped_column(String(16))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
