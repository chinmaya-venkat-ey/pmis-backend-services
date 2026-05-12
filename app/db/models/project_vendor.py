"""Read-only mirror of the ``project_vendors`` join table.

A project can map to one or more vendors. The daily-digest cron uses
this to resolve org-admin recipients: an org_admin of vendor V should
hear about any project mapped to V.
"""
from sqlalchemy import Column, ForeignKey, String

from ..session import Base


class ProjectVendorModel(Base):
    __tablename__ = "project_vendors"

    # In production this row exists with additional columns (vendor_code,
    # created_at, …). We only declare the join keys the cron uses.
    project_id = Column(
        String(36), ForeignKey("projects.id"),
        primary_key=True, nullable=False, index=True,
    )
    vendor_id = Column(
        String(36), primary_key=True, nullable=False, index=True,
    )
