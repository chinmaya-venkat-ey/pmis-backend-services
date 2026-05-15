"""Subtask SQLAlchemy model — owned by pmis-project-management.

Doc-24 nesting: `task_id` always points at the ROOT task; `parent_subtask_id`
is NULL for top-level children, non-NULL for nested children. The XOR semantics:
  - parent_subtask_id IS NULL  ⇔ child of task_id directly
  - parent_subtask_id IS NOT NULL ⇔ child of another subtask

Two partial unique indexes enforce position uniqueness per parent:
  - (task_id, position) where parent_subtask_id IS NULL    (top-level)
  - (parent_subtask_id, position) where parent_subtask_id IS NOT NULL  (nested)

Nesting depth is capped by settings.subtask_max_nesting_depth (service-layer).
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


class Subtask(Base):
    __tablename__ = "subtasks"
    __table_args__ = (
        CheckConstraint(
            "type IS NULL OR type IN ('standard', 'resource', 'transactional')",
            name="ck_subtasks_type",
        ),
        CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_subtasks_resource_mode",
        ),
        CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_subtasks_resource_count_positive",
        ),
        Index("idx_subtasks_task_live", "task_id", "deleted_at"),
        Index("idx_subtasks_task_position", "task_id", "position"),
        Index("idx_subtasks_project_live", "project_id", "deleted_at"),
        Index("ix_subtasks_parent_subtask_id", "parent_subtask_id"),
        Index(
            "uq_subtasks_task_position_top_live",
            "task_id", "position",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND parent_subtask_id IS NULL"
            ),
        ),
        Index(
            "uq_subtasks_subtask_position_live",
            "parent_subtask_id", "position",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND parent_subtask_id IS NOT NULL"
            ),
        ),
        Index("ix_subtasks_assigned_to", "assigned_to"),
        Index("ix_subtasks_status", "status"),
        Index("ix_subtasks_priority", "priority"),
        Index("ix_subtasks_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("project.tasks.id"))
    parent_subtask_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey(
            "project.subtasks.id",
            name="fk_subtasks_parent_subtask_id",
            use_alter=True,
        ),
    )

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

    assigned_to: Mapped[Optional[str]] = mapped_column(String(36))  # logical FK to users.users.id

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
