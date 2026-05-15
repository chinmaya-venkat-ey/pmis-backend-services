"""Cross-schema READ-ONLY mirror declarations for pmis-notification-management.

These classes describe tables OWNED BY OTHER SERVICES. notification-svc reads
them via SQL JOINs (for dispatch's template lookup and the daily-digest cron)
but NEVER writes to them. The owning service is the authoritative writer.

ALL mirrors are declared on `MirrorBase`, NOT `Base`, so they are excluded
from this service's alembic autogenerate (see alembic/env.py:include_object).

Canonical locations (where to make schema changes):

  masters.notification_templates    → services/pmis-masters-management/app/models/notification_template.py
                                       (moved here per Q3; was in notification-svc pre-refactor)

  users.users                       → services/pmis-user-management/app/models/user.py
  users.user_role_assignments       → services/pmis-user-management/app/models/user_role_assignment.py
  users.role_permissions            → services/pmis-user-management/app/models/role_permission.py
  users.roles                       → services/pmis-user-management/app/models/role.py
  users.revoked_tokens              → services/pmis-user-management/app/models/revoked_token.py

  project.projects                  → services/pmis-project-management/app/models/project.py
  project.milestones                → services/pmis-project-management/app/models/milestone.py
  project.activities                → services/pmis-project-management/app/models/activity.py
  project.project_vendors           → services/pmis-project-management/app/models/project_vendor.py

WARNING: Column-shape changes here MUST be replicated in the canonical model.
Q24 CI drift test (services/pmis-user-management/tests/test_cross_schema_drift.py)
catches divergence between this file and the canonical declarations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


# =========================================================================
# masters.notification_templates  — for dispatch + cron template lookup
# =========================================================================
class NotificationTemplate(MirrorBase):
    """Read-only mirror of masters.notification_templates (Q3)."""

    __tablename__ = "notification_templates"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_kind: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(16), index=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    is_html: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# =========================================================================
# users.*  — for daily-digest recipient resolution + role-based scoping
# =========================================================================
class User(MirrorBase):
    """Read-only mirror of users.users."""

    __tablename__ = "users"
    __table_args__ = {"schema": "users"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_code: Mapped[Optional[str]] = mapped_column(String(16))
    login: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(64))
    last_name: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))
    division: Mapped[Optional[str]] = mapped_column(String(64))
    phone_number: Mapped[Optional[str]] = mapped_column(String(32))
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Role(MirrorBase):
    """Read-only mirror of users.roles."""

    __tablename__ = "roles"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRoleAssignment(MirrorBase):
    """Read-only mirror of users.user_role_assignments (Doc-41 scoped RBAC)."""

    __tablename__ = "user_role_assignments"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)


# =========================================================================
# project.*  — for daily-digest upcoming-deadline scan
# =========================================================================
class Project(MirrorBase):
    """Read-only mirror of project.projects."""

    __tablename__ = "projects"
    __table_args__ = {"schema": "project"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_code: Mapped[Optional[str]] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Milestone(MirrorBase):
    """Read-only mirror of project.milestones."""

    __tablename__ = "milestones"
    __table_args__ = {"schema": "project"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Activity(MirrorBase):
    """Read-only mirror of project.activities."""

    __tablename__ = "activities"
    __table_args__ = {"schema": "project"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    milestone_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProjectVendor(MirrorBase):
    """Read-only mirror of project.project_vendors (M:N project↔vendor)."""

    __tablename__ = "project_vendors"
    __table_args__ = {"schema": "project"}

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String(36), primary_key=True)
