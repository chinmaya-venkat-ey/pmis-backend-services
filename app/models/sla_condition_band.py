"""SlaConditionBand — severity band definitions for band_accumulation and point_accumulation.

rate_percent: used by band_accumulation (BSP/MSIP) — LD rate per unit in band.
points_contribution: used by point_accumulation (MSAP/PMU) — points earned per interval.
  Can be NEGATIVE (MSAP severity 0 = -2 points, meaning reward).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaConditionBand(Base):
    __tablename__ = "sla_condition_bands"
    __table_args__ = (
        Index("ix_sla_cond_bands_sla_id", "sla_id"),
        Index("ix_sla_cond_bands_sla_metric", "sla_id", "metric_key"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    band_label: Mapped[str] = mapped_column(String(50), nullable=False)
    range_min: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    range_max: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    range_unit: Mapped[Optional[str]] = mapped_column(String(30))
    rate_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    points_contribution: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    fixed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # G19: compound 2D bands — rows sharing the same band_group_id must ALL be satisfied
    # simultaneously for that severity to fire (AND logic within group, OR between groups).
    band_group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
