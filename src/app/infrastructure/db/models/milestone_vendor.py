"""Association table: a milestone may reference vendors (a subset of the
project's vendors). Composite primary key on (milestone_id, vendor_id).

User-mgmt note: this table is owned by the monolith. We map it here
(without FK constraints) so vendor_repository's import chain works
without requiring monolith-only tables (milestones) to exist in the
local SQLite test DB. The monolith maintains referential integrity
on the shared Postgres."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, String
from ..utc_datetime import UtcDateTime
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MilestoneVendorModel(Base):
    __tablename__ = "milestone_vendors"

    # FK constraints stripped in this repo — user-mgmt never writes
    # this table; the monolith does. Stripping the FKs lets SQLite
    # test create_all succeed without milestones / vendors tables.
    milestone_id = Column(String(36), primary_key=True, index=True)
    vendor_id = Column(String(36), primary_key=True, index=True)
    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_milestone_vendors_milestone", "milestone_id"),
        Index("idx_milestone_vendors_vendor", "vendor_id"),
    )

    def __repr__(self) -> str:
        return f"<MilestoneVendorModel(milestone_id='{self.milestone_id}', vendor_id='{self.vendor_id}')>"
