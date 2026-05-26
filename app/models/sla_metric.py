"""SlaMetric — one row per metric/target within an SLA definition.

BSP dual-metric SLAs (FNIR+FPIR) have two rows. is_primary=False marks
guard/secondary metrics that don't directly generate LD.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaMetric(Base):
    __tablename__ = "sla_metrics"
    __table_args__ = (
        Index("ix_sla_metrics_sla_id", "sla_id"),
        Index("ix_sla_metrics_sla_metric_key", "sla_id", "metric_key", unique=True),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    target_numeric: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    target_date: Mapped[Optional[date]] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="LOWER_BETTER")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
