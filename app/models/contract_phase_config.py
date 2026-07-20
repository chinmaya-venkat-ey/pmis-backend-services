"""ContractPhaseConfig — deliverable→phase map per contract type.

Seed table used to (a) enforce RFP §5.28.2.a phase-gating (no resource
SLA on a Phase-1 activity) and (b) tell QuarterlySettlementService
whether QGR applies for the phase (Phase 1 only per §5.23.2).

One row per (contract_type, deliverable_code). PMU is seeded first (Step
2 of the rollout); BSP/MSAP/MSIP land in their own seed migrations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean, DateTime, Index, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContractPhaseConfig(Base):
    __tablename__ = "contract_phase_config"
    __table_args__ = (
        UniqueConstraint(
            "contract_type", "deliverable_code",
            name="uq_contract_phase_config",
        ),
        Index("ix_contract_phase_config_type", "contract_type"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_type: Mapped[str] = mapped_column(String(20), nullable=False)
    deliverable_code: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    qgr_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    # 'MILESTONE' | 'QUARTERLY' | 'ANNUAL'
    payment_cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
