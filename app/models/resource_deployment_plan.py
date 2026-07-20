"""ResourceDeploymentPlan — the missing staffing plan.

RFP §5.25.2.a mentions "resources deployed and man month rate" as the
basis for staff-cost payment. The current DB has per-activity resource
sidecars (activity_resources / task_resources / subtask_resources) but
no consultant-level monthly plan. NpqpService needs that plan to compute
F = Σ MP for the quarter.

One row per resource per project. ``monthly_rate`` is R in the RFP
formula ``MP = R × (1 − L/N)``. ``deployment_start`` / ``end`` bound the
months this resource contributes to F.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Date, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ResourceDeploymentPlan(Base):
    __tablename__ = "resource_deployment_plan"
    __table_args__ = (
        Index("ix_rdp_project", "project_id"),
        Index("ix_rdp_project_status", "project_id", "status"),
        Index("ix_rdp_window", "deployment_start", "deployment_end"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(120))
    designation: Mapped[Optional[str]] = mapped_column(String(120))
    monthly_rate: Mapped[Decimal] = mapped_column(NUMERIC(18, 2), nullable=False)
    deployment_start: Mapped[date] = mapped_column(Date, nullable=False)
    deployment_end: Mapped[Optional[date]] = mapped_column(Date)
    phase: Mapped[Optional[str]] = mapped_column(String(24))
    linked_resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    linked_resource_kind: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'ACTIVE'"),
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
