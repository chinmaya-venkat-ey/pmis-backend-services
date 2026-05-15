"""milestone_vendors — M:N milestones ↔ masters.vendors.

vendor_id is a logical FK to `masters.vendors.id`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MilestoneVendor(Base):
    __tablename__ = "milestone_vendors"
    __table_args__ = (
        Index("ix_milestone_vendors_milestone_id", "milestone_id"),
        Index("ix_milestone_vendors_vendor_id", "vendor_id"),
        {"schema": "project"},
    )

    milestone_id: Mapped[str] = mapped_column(
        ForeignKey("project.milestones.id"), primary_key=True,
    )
    vendor_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # logical FK
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
