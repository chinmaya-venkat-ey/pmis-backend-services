"""user_permissions join table — direct (additive) permission grants per user.

Independent of role assignments. The effective permission set is the
UNION of role-derived and direct grants (see RbacRepository).

WARNING: Mirrored in services/pmis-masters-management/app/models/_cross_schema.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserPermission(Base):
    __tablename__ = "user_permissions"
    __table_args__ = (
        Index("ix_user_permissions_user_id", "user_id"),
        Index("ix_user_permissions_permission_code", "permission_code"),
        {"schema": "users"},
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.users.id"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("users.permissions.code"), primary_key=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.users.id"),
    )
