"""Association table: a milestone may reference vendors (a subset of the
project's vendors). Composite primary key on (milestone_id, vendor_id)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MilestoneVendorModel(Base):
    __tablename__ = "milestone_vendors"

    milestone_id = Column(
        String(36),
        ForeignKey("milestones.id"),
        primary_key=True,
        index=True,
    )
    vendor_id = Column(
        String(36),
        ForeignKey("vendors.id"),
        primary_key=True,
        index=True,
    )
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_milestone_vendors_milestone", "milestone_id"),
        Index("idx_milestone_vendors_vendor", "vendor_id"),
    )

    def __repr__(self) -> str:
        return f"<MilestoneVendorModel(milestone_id='{self.milestone_id}', vendor_id='{self.vendor_id}')>"
