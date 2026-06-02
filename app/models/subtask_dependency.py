"""subtask_dependencies — directed edge (subtask A dependsOn B)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SubtaskDependency(Base):
    __tablename__ = "subtask_dependencies"
    __table_args__ = (
        Index("ix_subtask_dep_from", "from_subtask_id"),
        Index("ix_subtask_dep_to", "to_subtask_id"),
        {"schema": "project"},
    )

    from_subtask_id: Mapped[str] = mapped_column(
        ForeignKey("project.subtasks.id"), primary_key=True,
    )
    to_subtask_id: Mapped[str] = mapped_column(
        ForeignKey("project.subtasks.id"), primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
