"""Contract — top-level contract entity."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        Index("ix_contracts_contract_ref", "contract_ref", unique=True),
        Index("ix_contracts_status", "status"),
        Index("ix_contracts_vendor_name", "vendor_name"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    total_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    # G18: valid values: ACTIVE | PROBATION | SUSPENDED | EXPIRED | TERMINATED
    # PROBATION: BSP SLA 001/003 — all transactions non-payable; used for accuracy measurement only.
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    quarterly_ld_cap_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
