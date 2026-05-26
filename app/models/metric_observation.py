"""MetricObservation — a single periodic measurement for one metric of one SLA.

additional_inputs (JSONB) holds context-specific data the evaluation engine
needs but that doesn't fit a normalized column:
  WAC SLAs       : {"num_applications": 10}
  Uptime SLAs    : {"planned_downtime_minutes": 60}
  TAT SLAs       : {"defect_complexity": "HIGH", "defect_type": "BLOCKER"}
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MetricObservation(Base):
    __tablename__ = "metric_observations"
    __table_args__ = (
        Index("ix_metric_obs_sla_id", "sla_id"),
        Index("ix_metric_obs_status", "status"),
        Index("ix_metric_obs_period", "period_start", "period_end"),
        UniqueConstraint("sla_id", "metric_key", "period_start", "period_end", name="uq_metric_obs_sla_key_period"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    observed_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    observed_unit: Mapped[str] = mapped_column(String(30), nullable=False)
    baseline_used: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    excluded_from_sla: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[Optional[str]] = mapped_column(String(100))
    additional_inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    data_source: Mapped[Optional[str]] = mapped_column(String(30))
    submitted_by: Mapped[Optional[str]] = mapped_column(String(36))
    approved_by: Mapped[Optional[str]] = mapped_column(String(36))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
