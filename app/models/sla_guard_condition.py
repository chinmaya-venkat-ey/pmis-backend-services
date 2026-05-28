"""SlaGuardCondition — auto-exclude / suspend / probation rules per SLA."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaGuardCondition(Base):
    __tablename__ = "sla_guard_conditions"
    __table_args__ = (
        Index("ix_sla_guard_conditions_sla_id", "sla_id"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)
    threshold_value: Mapped[Decimal] = mapped_column(NUMERIC(18, 6), nullable=False)
    threshold_unit: Mapped[Optional[str]] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    action_description: Mapped[Optional[str]] = mapped_column(Text)
    guard_group_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
