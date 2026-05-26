"""Cross-schema READ-ONLY mirror declarations for pmis-contract-management.

Tables OWNED BY OTHER SERVICES that contract-svc reads:

  users.* — auth + RBAC (every request via AuthMiddleware)
    - users.users
    - users.roles
    - users.user_roles                  (legacy global tier)
    - users.user_role_assignments       (Doc-41 scoped tier)
    - users.role_permissions
    - users.user_permissions
    - users.revoked_tokens

All on `MirrorBase` — excluded from alembic autogenerate.

Canonical location: services/pmis-user-management/app/models/*
Schema changes there MUST be replicated here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


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
