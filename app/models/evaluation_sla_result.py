"""EvaluationSlaResult — per-SLA outcome within an evaluation run.

band_breakdown (JSONB) stores the detailed computation trace:
  band_accumulation: [{"band":"AMBER","units":45,"rate_pct":0.05,"ld_pct":0.0616}]
  point_accumulation: {"points_accumulated":6,"intervals":[...]}
  wac: {"wac_value":0.52,"baseline":0.47,"deviation_pct":10.6,"severity":2}

formula_snapshot records the formula_type + params at evaluation time for audit.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EvaluationSlaResult(Base):
    __tablename__ = "evaluation_sla_results"
    __table_args__ = (
        Index("ix_eval_sla_results_evaluation_id", "evaluation_id"),
        Index("ix_eval_sla_results_sla_id", "sla_id"),
        Index("ix_eval_sla_results_is_breached", "is_breached"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    evaluation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.evaluation_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id"),
        nullable=False,
    )
    is_breached: Mapped[bool] = mapped_column(Boolean, nullable=False)
    breach_severity: Mapped[Optional[str]] = mapped_column(String(20))
    computed_ld_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    computed_ld_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    band_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB)
    formula_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
