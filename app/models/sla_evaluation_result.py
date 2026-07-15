"""SlaEvaluationResult — one persisted SLA evaluation, per mapping, per day.

The daily cron evaluates every active mapping and writes one row here. This
is the historical record the dashboard and the project cost page read back
(aggregated), and the source of month-over-month SLA trends.

Design notes
------------
* **Rich status, not a bare boolean.** ``status`` captures the full picture
  (compliant / breached / at_risk / pending_observation / excluded /
  not_due); ``met`` and ``breached`` are convenience projections for cheap
  counting. The verdict is *formula-aware* — a fixed_escalation breach shows
  up as a ``breaches[]`` row with ``rate_percent > 0`` (its ``ld_percent`` is
  null), whereas point_accumulation/wac use ``severity_level``/``ld_percent``.
* **Hybrid display.** ``target_days`` / ``actual_days`` / ``delay_days`` are
  populated for date-based SLAs (``actual − target = delay``); null for
  %/count/WAC SLAs, which surface ``observed_value`` instead.
* **LD money.** ``ld_percent`` × the contractual base (per the SLA's
  ``ld_computation_base`` — quarterly/annual/fixed) → ``ld_amount``. The base
  actually used is recorded in ``ld_base_amount`` / ``ld_base_kind`` so the
  cost page's deduction is auditable.
* **Roll-up keys.** ``activity_id`` / ``milestone_id`` / ``project_id`` let us
  aggregate activity → milestone (cost page) → project (dashboard); the org
  roll-up is done in project-management, which owns project→vendor.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaEvaluationResult(Base):
    __tablename__ = "sla_evaluation_results"
    __table_args__ = (
        # One result per mapping per run-date — the cron is idempotent.
        UniqueConstraint("mapping_id", "evaluated_on", name="uq_sla_result_mapping_date"),
        Index("ix_sla_result_project_date", "project_id", "evaluated_on"),
        Index("ix_sla_result_activity", "activity_id"),
        Index("ix_sla_result_milestone", "milestone_id"),
        Index("ix_sla_result_status", "status"),
        Index("ix_sla_result_evaluated_on", "evaluated_on"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    mapping_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_activity_mappings.id", ondelete="CASCADE",
                   name="fk_sla_result_mapping"),
        nullable=False,
    )
    sla_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sla_ref: Mapped[Optional[str]] = mapped_column(String(64))
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    milestone_id: Mapped[Optional[str]] = mapped_column(String(36))
    project_id: Mapped[Optional[str]] = mapped_column(String(36))

    evaluated_on: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[Optional[date]] = mapped_column(Date)
    period_end: Mapped[Optional[date]] = mapped_column(Date)

    formula_type: Mapped[Optional[str]] = mapped_column(String(32))

    # Rich verdict + cheap projections.
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    met: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Engine output.
    severity_level: Mapped[Optional[int]] = mapped_column(Integer)
    accumulated_points: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    ld_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 4))

    # LD money (per E — contract-accurate base).
    ld_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    ld_base_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    ld_base_kind: Mapped[Optional[str]] = mapped_column(String(32))

    # Hybrid duration display (date-based SLAs only).
    target_days: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    actual_days: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    delay_days: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))

    observed_value: Mapped[Optional[Any]] = mapped_column(JSONB)
    breaches: Mapped[Optional[Any]] = mapped_column(JSONB)
    notes: Mapped[Optional[Any]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=datetime.utcnow, nullable=False,
    )
