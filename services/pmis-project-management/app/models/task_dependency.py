"""task_dependencies — directed edge (task A dependsOn B)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        Index("ix_task_dep_from", "from_task_id"),
        Index("ix_task_dep_to", "to_task_id"),
        {"schema": "project"},
    )

    from_task_id: Mapped[str] = mapped_column(
        ForeignKey("project.tasks.id"), primary_key=True,
    )
    to_task_id: Mapped[str] = mapped_column(
        ForeignKey("project.tasks.id"), primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
