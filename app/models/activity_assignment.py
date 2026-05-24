"""ActivityAssignment — per-activity user assignments for the Manage-Team UI.

role ∈ {'owner', 'owner_approver', 'division_user', 'division_approver'}

division_code is NULL for activity-level roles (owner / owner_approver) and
set to a masters.divisions.code value for division-specific roles
(division_user / division_approver).

user_id is a logical FK to users.users.id (no cross-schema constraint).
project_id is denormalised for cheap project-wide reads.
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActivityAssignment(Base):
    __tablename__ = "activity_assignments"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'owner_approver', 'division_user', 'division_approver')",
            name="ck_activity_assignments_role",
        ),
        UniqueConstraint(
            "activity_id", "user_id", "role", "division_code",
            name="uq_activity_assignments_activity_user_role_div",
        ),
        Index("idx_activity_assignments_activity", "activity_id"),
        Index("idx_activity_assignments_project", "project_id"),
        Index("idx_activity_assignments_user", "user_id"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(String(36))
    activity_id: Mapped[str] = mapped_column(ForeignKey("project.activities.id"))
    user_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(32))
    division_code: Mapped[Optional[str]] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
