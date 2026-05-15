"""Task SQLAlchemy model — owned by pmis-project-management.

Position is unique per LIVE row under (activity_id) — drives T{m}.{a}.{t}.
`type` retained as legacy column (Doc-38 deprecated for new writes).
`assigned_to` is a logical FK to `users.users.id`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "type IS NULL OR type IN ('standard', 'resource', 'transactional')",
            name="ck_tasks_type",
        ),
        CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_tasks_resource_mode",
        ),
        CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_tasks_resource_count_positive",
        ),
        Index("idx_tasks_activity_live", "activity_id", "deleted_at"),
        Index("idx_tasks_activity_position", "activity_id", "position"),
        Index("idx_tasks_project_live", "project_id", "deleted_at"),
        Index(
            "uq_tasks_activity_position_live",
            "activity_id", "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_tasks_assigned_to", "assigned_to"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_priority", "priority"),
        Index("ix_tasks_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))
    activity_id: Mapped[str] = mapped_column(ForeignKey("project.activities.id"))

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[Optional[str]] = mapped_column(String(20))   # legacy

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    position: Mapped[int] = mapped_column(Integer, default=0)
    resource_mode: Mapped[Optional[str]] = mapped_column(String(10))
    resource_count: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[Optional[str]] = mapped_column(String(32))
    priority: Mapped[Optional[str]] = mapped_column(String(16))

    # Logical FK to users.users.id (cross-schema).
    assigned_to: Mapped[Optional[str]] = mapped_column(String(36))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
