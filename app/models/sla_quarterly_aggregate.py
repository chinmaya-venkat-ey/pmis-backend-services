"""SlaQuarterlyAggregate — per-mapping quarterly rollup.

One row per (mapping, fiscal_year, quarter). This is where RFP §5.28.1.c
"reset at end of reporting interval" actually happens: the per-mapping
points accumulated across all evaluation_result rows in the quarter are
summed once, looked up on the LD ladder once, and yield a single
``ld_percent`` for that mapping in that quarter.

Downstream, SlaSettlementPeriod sums ld_percent across every mapping in
the project × quarter, caps at 10%, multiplies by PQP.

Writer: SlaComplianceService.rollup_quarterly (Phase B).
Reader: QuarterlySettlementService.close (Phase D) and the audit API.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaQuarterlyAggregate(Base):
    __tablename__ = "sla_quarterly_aggregate"
    __table_args__ = (
        UniqueConstraint(
            "mapping_id", "fiscal_year", "quarter",
            name="uq_sla_qtr_agg_mapping_quarter",
        ),
        Index(
            "ix_sla_qtr_agg_project_quarter",
            "project_id", "fiscal_year", "quarter",
        ),
        Index("ix_sla_qtr_agg_sla_ref", "sla_ref"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mapping_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_activity_mappings.id", ondelete="CASCADE"),
        nullable=False,
    )
    sla_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sla_ref: Mapped[Optional[str]] = mapped_column(String(64))
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..4
    quarter_start: Mapped[date] = mapped_column(Date, nullable=False)
    quarter_end: Mapped[date] = mapped_column(Date, nullable=False)

    accumulated_points: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(18, 4))
    derived_severity: Mapped[Optional[int]] = mapped_column(Integer)
    ld_percent: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(9, 4))

    source_result_ids: Mapped[Optional[list]] = mapped_column(ARRAY(String(36)))
    carried_forward: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    notes: Mapped[Optional[dict]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
