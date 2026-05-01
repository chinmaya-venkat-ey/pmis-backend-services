"""Association table: a project may have many vendors; a vendor can be on many projects.

Composite primary key on (project_id, vendor_id). Rows are added/removed in
bulk when the project's vendor list is set.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ProjectVendorModel(Base):
    __tablename__ = "project_vendors"

    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
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
        Index("idx_project_vendors_project", "project_id"),
        Index("idx_project_vendors_vendor", "vendor_id"),
    )

    def __repr__(self) -> str:
        return f"<ProjectVendorModel(project_id='{self.project_id}', vendor_id='{self.vendor_id}')>"
