"""SlaLookupRow — tier table rows for fixed_escalation (and point_accumulation LD table)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaLookupRow(Base):
    __tablename__ = "sla_lookup_rows"
    __table_args__ = (
        Index("ix_sla_lookup_rows_sla_id", "sla_id"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lookup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    lookup_value: Mapped[Decimal] = mapped_column(NUMERIC(18, 6), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
