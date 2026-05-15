"""subtask_resources — 1:1 sidecar for subtask staffing."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SubtaskResource(Base):
    __tablename__ = "subtask_resources"
    __table_args__ = (
        Index(
            "uq_subtask_resources_subtask_live",
            "subtask_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_subtask_resources_project_live", "project_id", "deleted_at"),
        Index("ix_subtask_resources_type_of_resource_id", "type_of_resource_id"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    subtask_id: Mapped[str] = mapped_column(ForeignKey("project.subtasks.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))

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

    type_of_resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    division: Mapped[Optional[str]] = mapped_column(String(32))
    division_other: Mapped[Optional[str]] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
