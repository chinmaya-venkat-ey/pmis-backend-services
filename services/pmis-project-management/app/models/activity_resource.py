"""activity_resources — 1:1 sidecar holding resource staffing details.

Unique-per-activity LIVE constraint via partial unique index. `type_of_resource_id`
is a logical FK to `masters.resource_types.id`. `division` is a logical FK
to `masters.divisions.code`.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActivityResource(Base):
    __tablename__ = "activity_resources"
    __table_args__ = (
        Index(
            "uq_activity_resources_activity_live",
            "activity_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_activity_resources_project_live", "project_id", "deleted_at"),
        Index("ix_activity_resources_type_of_resource_id", "type_of_resource_id"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("project.activities.id"),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.projects.id"),
    )

    resource_name: Mapped[str] = mapped_column(String(255))

    onboard_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_onboard_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    offboard_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_offboard_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    position: Mapped[Optional[str]] = mapped_column(String(255))
    designation: Mapped[Optional[str]] = mapped_column(String(255))
    job_role: Mapped[Optional[str]] = mapped_column(String(255))
    qualification: Mapped[Optional[str]] = mapped_column(String(255))
    experience_years: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 1))

    # Logical FK to masters.resource_types.id.
    type_of_resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    # Logical FK to masters.divisions.code.
    division: Mapped[Optional[str]] = mapped_column(String(32))
    division_other: Mapped[Optional[str]] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
