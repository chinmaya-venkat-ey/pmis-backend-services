"""role_permissions join table — which permission codes a role holds.

WARNING: Mirrored in services/pmis-masters-management/app/models/_cross_schema.py.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        Index("ix_role_permissions_role_id", "role_id"),
        Index("ix_role_permissions_permission_code", "permission_code"),
        {"schema": "users"},
    )

    role_id: Mapped[int] = mapped_column(
        ForeignKey("users.roles.id"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("users.permissions.code"), primary_key=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
