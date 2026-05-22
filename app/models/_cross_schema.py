"""Read-only mirror declarations for tables owned by other services.

file-svc reads from users.* for auth/RBAC only; it does not own these tables.
Excluded from alembic autogenerate.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


class User(MirrorBase):
    """Read-only mirror of users.users for auth hydration."""
    __tablename__ = "users"
    __table_args__ = {"schema": "users"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    login: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50))
    admin: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))


class Role(MirrorBase):
    """Read-only mirror of users.roles."""
    __tablename__ = "roles"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Permission(MirrorBase):
    """Read-only mirror of users.permissions."""
    __tablename__ = "permissions"
    __table_args__ = {"schema": "users"}

    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    label: Mapped[Optional[str]] = mapped_column(String(255))


class RolePermission(MirrorBase):
    """Read-only mirror of users.role_permissions."""
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": "users"}

    role_id: Mapped[int] = mapped_column(primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(100), primary_key=True)


class UserRoleAssignment(MirrorBase):
    """Read-only mirror of users.user_role_assignments."""
    __tablename__ = "user_role_assignments"
    __table_args__ = {"schema": "users"}

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36))
    role_id: Mapped[int]
    project_id: Mapped[Optional[str]] = mapped_column(String(36))


class RevokedToken(MirrorBase):
    """Read-only mirror of users.revoked_tokens."""
    __tablename__ = "revoked_tokens"
    __table_args__ = {"schema": "users"}

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36))
