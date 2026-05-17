"""milestone_dependencies — directed edge table (milestone A dependsOn B).

The application service enforces no-cycle. Composite PK on
(from_milestone_id, to_milestone_id) keeps the edge idempotent.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MilestoneDependency(Base):
    __tablename__ = "milestone_dependencies"
    __table_args__ = (
        Index("ix_milestone_dep_from", "from_milestone_id"),
        Index("ix_milestone_dep_to", "to_milestone_id"),
        {"schema": "project"},
    )

    from_milestone_id: Mapped[str] = mapped_column(
        ForeignKey("project.milestones.id"), primary_key=True,
    )
    to_milestone_id: Mapped[str] = mapped_column(
        ForeignKey("project.milestones.id"), primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
