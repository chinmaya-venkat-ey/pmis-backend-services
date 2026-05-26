"""SlaGuardCondition — threshold triggers that modify LD computation.

Actions: OBSERVATION_MODE | SUSPEND_LD | ESCALATE | EXEMPT
Example: BSP SLA 001 — FPIR > 0.5% → OBSERVATION_MODE
Example: BSP SLA 003 — delivered < 350K AND processed >= 98% → EXEMPT
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaGuardCondition(Base):
    __tablename__ = "sla_guard_conditions"
    __table_args__ = (
        Index("ix_sla_guard_conditions_sla_id", "sla_id"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)
    threshold_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    threshold_unit: Mapped[Optional[str]] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    action_description: Mapped[Optional[str]] = mapped_column(Text)
    # G17: AND-grouped guards — rows sharing the same guard_group_id are ANDed; groups are OR'd.
    guard_group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
