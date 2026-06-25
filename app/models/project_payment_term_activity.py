"""ProjectPaymentTermActivity — per-activity split of a milestone payment term.

A partial-payment milestone's payment term (``percent_of_payment`` of the
phase) is broken down across the milestone's activities: one row per activity,
each carrying its own ``percent_of_payment`` (same phase-percent basis). The
per-activity percents sum to the parent term's percent (enforced in the
service). One live row per (payment_term, activity).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectPaymentTermActivity(Base):
    __tablename__ = "project_payment_term_activities"
    __table_args__ = (
        Index("idx_pta_term_live", "payment_term_id", "deleted_at"),
        Index("ix_pta_activity_id", "activity_id"),
        Index(
            "uq_pta_term_activity_live",
            "payment_term_id", "activity_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "percent_of_payment IS NULL OR "
            "(percent_of_payment >= 0 AND percent_of_payment <= 100)",
            name="ck_pta_percent_range",
        ),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))
    payment_term_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_payment_terms.id")
    )
    activity_id: Mapped[str] = mapped_column(ForeignKey("project.activities.id"))
    percent_of_payment: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
