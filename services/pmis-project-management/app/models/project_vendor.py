"""project_vendors — M:N projects ↔ masters.vendors.

Vendor PK is a logical FK to `masters.vendors.id` (cross-schema; not
DB-enforced). The (project_id, vendor_id) composite is the natural PK.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectVendor(Base):
    __tablename__ = "project_vendors"
    __table_args__ = (
        Index("ix_project_vendors_project_id", "project_id"),
        Index("ix_project_vendors_vendor_id", "vendor_id"),
        {"schema": "project"},
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.projects.id"), primary_key=True,
    )
    # Logical FK to masters.vendors.id — not DB-enforced.
    vendor_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
