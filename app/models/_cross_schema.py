"""Cross-schema READ-ONLY mirror declarations for pmis-masters-management.

These classes describe tables OWNED BY OTHER SERVICES. masters-svc reads
them for:
  1. Auth middleware — JWT verification + permission hydration on every
     non-public request. (users.users, users.roles, users.user_roles,
     users.role_permissions, users.user_permissions, users.user_role_assignments,
     users.revoked_tokens)
  2. Catalog endpoints that join into other domains — e.g.
     /masters/vendors/{id}/projects/list joins masters.vendors to
     project.projects via project.project_vendors. (added as needed when
     the per-catalog routes are ported)

All declarations are on MirrorBase, excluded from alembic autogenerate.

Canonical locations:
  users.*    → services/pmis-user-management/app/models/* (pending; not yet ported)
  project.*  → services/pmis-project-management/app/models/* (pending)

WARNING: column-shape changes here MUST be replicated in the canonical
files. Q24 CI drift test will catch divergence once user-svc is ported.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


# =========================================================================
# users.* — auth + RBAC tables (read every request)
# =========================================================================

class User(MirrorBase):
    """Read-only mirror of users.users (canonical: pmis-user-management/app/models/user.py)."""

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
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Role(MirrorBase):
    __tablename__ = "roles"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRole(MirrorBase):
    """Legacy global-scope role assignments (pre-Doc-41)."""

    __tablename__ = "user_roles"
    __table_args__ = {"schema": "users"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class UserRoleAssignment(MirrorBase):
    """Doc-41 scoped RBAC."""

    __tablename__ = "user_role_assignments"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)


class Permission(MirrorBase):
    __tablename__ = "permissions"
    __table_args__ = {"schema": "users"}

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class RolePermission(MirrorBase):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "users"}

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(128), primary_key=True)


class UserPermission(MirrorBase):
    """Direct (additive) grants on a per-user basis."""

    __tablename__ = "user_permissions"
    __table_args__ = {"schema": "users"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(128), primary_key=True)


class RevokedToken(MirrorBase):
    __tablename__ = "revoked_tokens"
    __table_args__ = {"schema": "users"}

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# =========================================================================
# project.* — needed for /masters/vendors/{vendor_id}/projects/list
# Returns the slim project list a vendor is mapped to (FE vendor-detail page).
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
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProjectVendor(MirrorBase):
    """Mirror of project.project_vendors (M:N project↔vendor). Written to by master-svc when projectIds are supplied on vendor create/update."""

    __tablename__ = "project_vendors"
    __table_args__ = {"schema": "project"}

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
