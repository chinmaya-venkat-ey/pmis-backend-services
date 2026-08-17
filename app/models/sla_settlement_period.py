"""SlaSettlementPeriod — the quarter-close artifact.

One row per (project, fiscal_year, quarter). Persisted by
QuarterlySettlementService.close (Phase D). Encodes RFP §5.28.1.d.h:

    AQP = (PA − LD) + QGR
    LD  = min(Σ per-SLA LD %, 10%) × PQP        (PQP = F; QGR NOT in the LD base)
    NPQP = F + QGR                              (DELETED clause §5.28.1.d.e —
                                                 stored for display/audit only,
                                                 never the penalty base)

Lifecycle:
  open        — created lazily as evaluations flow in; provisional
  auto_closed — cron on quarter_end + 1 froze the numbers
  overridden  — finance role changed sum_ld_percent (with reason)
  invoiced    — payment page raised the invoice; row is immutable

``consequence_flags`` is BSP-facing (probation / non-payable) — unused for
PMU today, present in the schema so BSP evaluators need no migration.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Date, DateTime, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaSettlementPeriod(Base):
    __tablename__ = "sla_settlement_period"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "fiscal_year", "quarter",
            name="uq_sla_settlement_project_quarter",
        ),
        Index("ix_sla_settlement_status", "status"),
        Index("ix_sla_settlement_project", "project_id"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contract_type: Mapped[Optional[str]] = mapped_column(String(20))
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter_start: Mapped[date] = mapped_column(Date, nullable=False)
    quarter_end: Mapped[date] = mapped_column(Date, nullable=False)

    sum_ld_percent: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(9, 4))
    capped_ld_percent: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(9, 4))
    f_amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 2))
    qgr_amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 2))
    npqp: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 2))
    ld_amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 2))
    pa_amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 2))
    aqp_amount: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 2))

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'open'"),
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[Optional[str]] = mapped_column(String(36))
    override_reason: Mapped[Optional[str]] = mapped_column(Text)
    source_aggregate_ids: Mapped[Optional[list]] = mapped_column(ARRAY(String(36)))

    consequence_flags: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
