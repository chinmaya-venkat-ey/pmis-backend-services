"""Cross-schema READ-ONLY mirror declarations for pmis-project-management.

Tables OWNED BY OTHER SERVICES that project-svc reads:

  users.* — auth + RBAC (every request via AuthMiddleware)
    - users.users
    - users.roles
    - users.user_roles                  (legacy global tier)
    - users.user_role_assignments       (Doc-41 scoped tier)
    - users.role_permissions
    - users.user_permissions
    - users.revoked_tokens

  masters.* — picker/embed data for project / milestone / activity responses
    - masters.vendors
    - masters.divisions
    - masters.priorities
    - masters.resource_types
    - masters.project_categories
    - masters.activity_statuses
    - masters.milestone_statuses
    - masters.activity_types
    - masters.project_status_transitions

All on `MirrorBase` — excluded from alembic autogenerate.

Canonical locations:
  users.*    → services/pmis-user-management/app/models/*
  masters.*  → services/pmis-masters-management/app/models/*

WARNING: Schema changes in canonical models MUST be replicated here.
The Q24 drift test in pmis-user-management/tests/test_cross_schema_drift.py
catches divergence (once project-svc is added to its _PEER_SERVICES list).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


# =========================================================================
# users.* — read every request
# =========================================================================

class User(MirrorBase):
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
    division_other: Mapped[Optional[str]] = mapped_column(String(255))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Role(MirrorBase):
    __tablename__ = "roles"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class UserRole(MirrorBase):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "users"}

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class UserRoleAssignment(MirrorBase):
    __tablename__ = "user_role_assignments"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)


class RolePermission(MirrorBase):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "users"}

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(128), primary_key=True)


class UserPermission(MirrorBase):
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
# masters.* — picker / embed data
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


class Priority(MirrorBase):
    __tablename__ = "priorities"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class ResourceType(MirrorBase):
    __tablename__ = "resource_types"
    __table_args__ = {"schema": "masters"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectCategory(MirrorBase):
    __tablename__ = "project_categories"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_other: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(1024))


class ActivityType(MirrorBase):
    __tablename__ = "activity_types"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ActivityStatus(MirrorBase):
    __tablename__ = "activity_statuses"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MilestoneStatus(MirrorBase):
    __tablename__ = "milestone_statuses"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectStatusTransition(MirrorBase):
    """Edge in the project-status FSM. Round-7: gates by PERMISSION CODE.

    `permission_code` is the code the caller must hold to take this edge
    (scoped to the project or globally). NULL = no special permission required.
    """

    __tablename__ = "project_status_transitions"
    __table_args__ = {"schema": "masters"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(50))
    to_status: Mapped[str] = mapped_column(String(50))
    permission_code: Mapped[Optional[str]] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
