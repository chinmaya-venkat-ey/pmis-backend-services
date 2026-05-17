"""Role SQLAlchemy model — owned by pmis-user-management.

Doc-21B dropped the `permissions` JSON column (was inline list of codes);
permissions now live in role_permissions join table.

WARNING: Mirrored in services/pmis-{masters,project,notification}-management
/app/models/_cross_schema.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        Index("ix_roles_name", "name", unique=True),
        Index("ix_roles_builtin", "builtin"),
        {"schema": "users"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(String(1024))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
