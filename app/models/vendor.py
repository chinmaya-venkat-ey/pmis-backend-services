"""Vendor catalog — owned by pmis-masters-management.

Org-tier entity referenced from users.users.vendor_id,
users.user_role_assignments.organization_id, project.project_vendors,
project.milestone_vendors, project.activities.vendor_id.

Per Q1 confirmation: vendor stays NAMED `vendor` on the wire (FE renders
"Organization" label only). NO rename to organizations.

Ported from C:\\Programming\\PMIS\\PMIS-OpenProject\\app\\infrastructure\\db\\models\\vendor.py:31
with SQLAlchemy 2.0 patterns and cross-schema FK from deleted_by → users.users.id.

WARNING: This model is MIRRORED in:
  - services/pmis-user-management/app/models/_cross_schema.py (VendorModel)
  - services/pmis-project-management/app/models/_cross_schema.py (Vendor)
  - services/pmis-notification-management/app/models/_cross_schema.py (NOT in original
    notification mirror — vendor is referenced indirectly via project.project_vendors)
Column changes here MUST be replicated.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        Index("ix_vendors_name", "name", unique=True),
        Index("ix_vendors_vendor_code", "vendor_code", unique=True),
        Index("ix_vendors_active", "active"),
        Index("ix_vendors_email", "email"),
        Index("ix_vendors_deleted_at", "deleted_at"),
        Index("idx_vendors_active_name", "active", "name"),
        Index("idx_vendors_created_at", "created_at"),
        {"schema": "masters"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # Doc 25: human-readable code separate from UUID.
    vendor_code: Mapped[Optional[str]] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Contact details (doc 18) — all nullable.
    email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_person: Mapped[Optional[str]] = mapped_column(String(255))
    phone_number: Mapped[Optional[str]] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Soft-delete (doc 17). `deleted_by` is a LOGICAL reference to users.users.id
    # but NOT a DB-level foreign key — the constraint would be cross-schema +
    # cross-service (users-svc owns users.users; that table isn't guaranteed to
    # exist when masters-svc runs its initial migration). App code populates
    # this from request.state.user_id; correctness is enforced at the app layer.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(String(36))
