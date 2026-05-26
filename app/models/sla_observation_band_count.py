"""SlaObservationBandCount — per-band unit counts for a metric observation.

Required for band_accumulation SLAs where LD = Σ(units_in_band × band_rate%) / period_units.
unit_count = number of days (BSP) or instances in the given severity band.
Not used for point_accumulation or wac SLAs.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaObservationBandCount(Base):
    __tablename__ = "sla_observation_band_counts"
    __table_args__ = (
        Index("ix_sla_obs_band_counts_observation_id", "observation_id"),
        UniqueConstraint("observation_id", "band_id", name="uq_obs_band_count"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    observation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.metric_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    band_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_condition_bands.id"),
        nullable=False,
    )
    band_label: Mapped[str] = mapped_column(String(50), nullable=False)
    unit_count: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
