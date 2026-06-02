"""activity_dependencies — directed edge (activity A dependsOn B)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActivityDependency(Base):
    __tablename__ = "activity_dependencies"
    __table_args__ = (
        Index("ix_activity_dep_from", "from_activity_id"),
        Index("ix_activity_dep_to", "to_activity_id"),
        {"schema": "project"},
    )

    from_activity_id: Mapped[str] = mapped_column(
        ForeignKey("project.activities.id"), primary_key=True,
    )
    to_activity_id: Mapped[str] = mapped_column(
        ForeignKey("project.activities.id"), primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
