"""SlaLookupRow — key→value lookup table for fixed_escalation SLAs.

Simple keys: '1-30', '31-60', '>90' (delay days → LD%).
Composite keys: 'BLOCKER:LOW_MODERATE', 'BLOCKER:HIGH' (defect_type × complexity → TAT days).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaLookupRow(Base):
    __tablename__ = "sla_lookup_rows"
    __table_args__ = (
        Index("ix_sla_lookup_rows_sla_id", "sla_id"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    lookup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    lookup_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
