"""cost_item_milestones — M:N project_cost_items ↔ project.milestones.

A ``fixed`` cost row binds a bundle of milestones; this join table holds
the mapping. Pure association rows (no soft-delete): they are replaced
wholesale when a cost item's milestone set changes, and hard-deleted when
the cost item is removed.

A milestone belongs to exactly ONE phase across the project — enforced in
the service layer (a milestone may not appear under two cost items of
different phases).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CostItemMilestone(Base):
    __tablename__ = "cost_item_milestones"
    __table_args__ = (
        Index("ix_cost_item_milestones_cost_item_id", "cost_item_id"),
        Index("ix_cost_item_milestones_milestone_id", "milestone_id"),
        {"schema": "project"},
    )

    cost_item_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_cost_items.id"), primary_key=True,
    )
    milestone_id: Mapped[str] = mapped_column(
        ForeignKey("project.milestones.id"), primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
