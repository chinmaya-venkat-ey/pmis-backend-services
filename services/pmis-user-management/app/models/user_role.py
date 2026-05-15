"""user_roles join table — LEGACY GLOBAL-SCOPE role assignments.

Pre-Doc-41 model. Still queried (e.g. admin-tier scan in project-svc admin
filters) but new writes go to user_role_assignments which carries scope.

WARNING: Mirrored in services/pmis-{masters,project,notification}-management.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        Index("ix_user_roles_user_id", "user_id"),
        Index("ix_user_roles_role_id", "role_id"),
        {"schema": "users"},
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.users.id"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("users.roles.id"), primary_key=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.users.id"),
    )
