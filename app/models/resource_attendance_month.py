"""ResourceAttendanceMonth — L in the RFP §5.25.2 MP formula.

One row per (resource_deployment, year, month). ``unpaid_leaves`` is the
L that appears in ``MP = R × (1 − L/N)``. Missing rows are read as
"assume full presence" by NpqpService (fail-open per the plan's design
principle).

Two sources:
  * ``manual``    — ops enters via the monthly attendance form (Phase G).
  * ``biometric`` — batch import from UIDAI biometric system (feature
                    flag off today; ships when the export format is
                    available).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ResourceAttendanceMonth(Base):
    __tablename__ = "resource_attendance_month"
    __table_args__ = (
        UniqueConstraint(
            "resource_deployment_id", "year", "month",
            name="uq_ram_resource_month",
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_ram_month_range"),
        Index("ix_ram_year_month", "year", "month"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    resource_deployment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("project.resource_deployment_plan.id", ondelete="CASCADE"),
        nullable=False,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    unpaid_leaves: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(6, 2))
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'manual'"),
    )
    recorded_by: Mapped[Optional[str]] = mapped_column(String(36))
    recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
