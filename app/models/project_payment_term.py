"""ProjectPaymentTerm — a row of the Project-Finance "Project Term" table.

Payment terms are phase-based: for each ``phase`` the milestones bound to
that phase (via the Project-Cost rows) are paid out by ``percent_of_payment``
at a chosen ``frequency_code`` (logical FK masters.frequencies.code). The
``value`` is derived on response — ``percent_of_payment / 100 × phase fixed
total`` — never stored.

A milestone is paid once across the project (partial unique
``uq_payment_terms_project_milestone_live``). Per-project ``position`` is
unique among LIVE rows. Fields are intentionally nullable for now.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectPaymentTerm(Base):
    __tablename__ = "project_payment_terms"
    __table_args__ = (
        Index("idx_payment_terms_project_live", "project_id", "deleted_at"),
        Index("idx_payment_terms_project_phase", "project_id", "phase"),
        Index(
            "uq_payment_terms_project_position_live",
            "project_id", "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # A milestone is paid out once across the project.
        Index(
            "uq_payment_terms_project_milestone_live",
            "project_id", "milestone_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_payment_terms_milestone_id", "milestone_id"),
        Index("ix_payment_terms_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))

    phase: Mapped[Optional[int]] = mapped_column(Integer)
    milestone_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("project.milestones.id")
    )
    # Logical FK to masters.frequencies.code (cross-schema). Nullable for now.
    frequency_code: Mapped[Optional[str]] = mapped_column(String(32))
    percent_of_payment: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    position: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
