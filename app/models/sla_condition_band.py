"""SlaConditionBand — per-band configuration for band_accumulation and point_accumulation."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaConditionBand(Base):
    __tablename__ = "sla_condition_bands"
    __table_args__ = (
        Index("ix_sla_condition_bands_sla_id", "sla_id"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    band_label: Mapped[str] = mapped_column(String(50), nullable=False)
    range_min: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 6))
    range_max: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 6))
    range_unit: Mapped[Optional[str]] = mapped_column(String(30))
    severity_level: Mapped[Optional[int]] = mapped_column(Integer)   # point_accumulation
    rate_percent: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))  # band_accumulation
    points_contribution: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 4))
    fixed_amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 6))
    band_group_id: Mapped[Optional[int]] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
