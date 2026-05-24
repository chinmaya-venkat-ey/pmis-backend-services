"""ProjectOwnership — project-level owner / approver assignments.

Distinct from the org-tier project_admin role in users.user_role_assignments.
This captures the named individuals shown in the 'Project Owner' section of the
Manage-Team UI (role ∈ {'project_owner', 'approver'}).

user_id is a logical FK to users.users.id (no cross-schema constraint).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectOwnership(Base):
    __tablename__ = "project_ownership"
    __table_args__ = (
        CheckConstraint(
            "role IN ('project_owner', 'approver')",
            name="ck_project_ownership_role",
        ),
        UniqueConstraint(
            "project_id", "user_id", "role",
            name="uq_project_ownership_project_user_role",
        ),
        Index("idx_project_ownership_project", "project_id"),
        Index("idx_project_ownership_user", "user_id"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))
    user_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
