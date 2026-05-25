"""Activity SQLAlchemy model — owned by pmis-project-management.

Denormalized `project_id` for cheap "everything under project X" reads.
Position is unique per LIVE row under (milestone_id) — drives A{m}.{a} labels.

`vendor_id` is a logical FK to `masters.vendors.id` (cross-schema).
`status` is a logical FK to `masters.activity_statuses.code`.
`owner_division` / `concerned_division` are logical FKs to `masters.divisions.code`.
`concerned_divisions` is a JSON list of division codes (Doc-39).
`type` column kept for legacy reads only (Doc-38 deprecated).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(
            "type IS NULL OR type IN ('standard', 'resource', 'transactional')",
            name="ck_activities_type",
        ),
        CheckConstraint(
            "resource_mode IS NULL OR resource_mode IN ('count', 'details')",
            name="ck_activities_resource_mode",
        ),
        CheckConstraint(
            "resource_count IS NULL OR resource_count >= 1",
            name="ck_activities_resource_count_positive",
        ),
        Index("idx_activities_milestone_live", "milestone_id", "deleted_at"),
        Index("idx_activities_milestone_position", "milestone_id", "position"),
        Index("idx_activities_project_live", "project_id", "deleted_at"),
        Index(
            "uq_activities_milestone_position_live",
            "milestone_id", "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_activities_vendor_id", "vendor_id"),
        Index("ix_activities_owner_division", "owner_division"),
        Index("ix_activities_status", "status"),
        Index("ix_activities_priority", "priority"),
        Index("ix_activities_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.projects.id"),
    )
    milestone_id: Mapped[str] = mapped_column(
        ForeignKey("project.milestones.id"),
    )

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    type: Mapped[Optional[str]] = mapped_column(String(20))     # legacy; Doc-38 deprecated

    owner_division: Mapped[Optional[str]] = mapped_column(String(32))
    # Free-text companion for owner_division. Required when owner_division
    # is the catalog code 'others'; must stay NULL/empty otherwise. Enforced
    # at the service layer (validate_division_other_pair).
    owner_division_other: Mapped[Optional[str]] = mapped_column(String(255))
    concerned_division: Mapped[Optional[str]] = mapped_column(String(32))
    concerned_divisions: Mapped[Optional[list[Any]]] = mapped_column(JSONB)
    # Free-text companion when concerned_divisions list contains 'others'.
    # Single field (one description suffices regardless of how many other
    # divisions are listed). Enforced at the service layer.
    concerned_division_other: Mapped[Optional[str]] = mapped_column(String(255))
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))  # logical FK

    priority: Mapped[Optional[str]] = mapped_column(String(16))

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    position: Mapped[int] = mapped_column(Integer, default=0)

    resource_mode: Mapped[Optional[str]] = mapped_column(String(10))
    resource_count: Mapped[Optional[int]] = mapped_column(Integer)

    status: Mapped[Optional[str]] = mapped_column(String(32))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
