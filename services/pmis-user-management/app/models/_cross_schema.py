"""Cross-schema READ-ONLY mirror declarations for pmis-user-management.

user-svc reads these for:
  - Caller-vs-target gates (Doc-44): walking project → vendor when granting
    org-scoped roles
  - `assignable-users` queries: which users a project_admin can assign
  - User-response embedding: vendor_name + project list in the user-detail page
  - Daily-digest cron support (notification-svc reads users.* cross-schema
    independently; user-svc doesn't drive that)

ALL on `MirrorBase` — excluded from alembic autogenerate.

Canonical locations:
  masters.vendors, masters.divisions
    → services/pmis-masters-management/app/models/{vendor,division}.py
  project.projects, project.project_vendors
    → services/pmis-project-management/app/models/{project,project_vendor}.py
    (pending — project-svc not yet ported; declarations here will line up
    once it's ported)

WARNING: Schema changes in the canonical models MUST be replicated here.
Q24 CI drift test (this service has the canonical test —
tests/test_cross_schema_drift.py — to be written in next batch) catches drift.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


# =========================================================================
# masters.vendors — org-tier entity referenced by users.vendor_id and
# users.user_role_assignments.organization_id
# =========================================================================
class Vendor(MirrorBase):
    __tablename__ = "vendors"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vendor_code: Mapped[Optional[str]] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_person: Mapped[Optional[str]] = mapped_column(String(255))
    phone_number: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(String(36))


# =========================================================================
# masters.divisions — division code referenced by users.division
# =========================================================================
class Division(MirrorBase):
    __tablename__ = "divisions"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_other: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str] = mapped_column(String(50))


# =========================================================================
# project.* — used for assignable-users queries + scoped RBAC walks +
# user response embedding (projects[] on the user-detail response)
# =========================================================================
class Project(MirrorBase):
    __tablename__ = "projects"
    __table_args__ = {"schema": "project"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_code: Mapped[Optional[str]] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProjectVendor(MirrorBase):
    """M:N project ↔ vendor mapping. Used by `_project_owning_vendors` in the
    Doc-44 caller-vs-target gate."""

    __tablename__ = "project_vendors"
    __table_args__ = {"schema": "project"}

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String(36), primary_key=True)
