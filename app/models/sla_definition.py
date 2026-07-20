"""SlaDefinition — SLA master template (not bound to any project/contract instance)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaDefinition(Base):
    __tablename__ = "sla_definitions"
    __table_args__ = (
        Index("ix_sla_def_project_id", "project_id"),
        Index("ix_sla_def_contract_type", "contract_type"),
        Index("ix_sla_def_formula_id", "formula_id"),
        Index("ix_sla_def_status", "status"),
        Index("ix_sla_def_category", "category"),
        UniqueConstraint("sla_ref", name="ix_sla_def_sla_ref"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[Optional[str]] = mapped_column(String(36))
    contract_type: Mapped[Optional[str]] = mapped_column(String(20))
    milestone_id: Mapped[Optional[str]] = mapped_column(String(36))
    activity_id: Mapped[Optional[str]] = mapped_column(String(36))
    formula_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sla_ref: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    measurement_interval: Mapped[str] = mapped_column(String(30), nullable=False, server_default="MONTHLY")
    reporting_interval: Mapped[str] = mapped_column(String(30), nullable=False, server_default="QUARTERLY")
    baseline_type: Mapped[str] = mapped_column(String(30), nullable=False, server_default="STATIC")
    compound_metric_rule: Mapped[str] = mapped_column(String(30), nullable=False, server_default="INDEPENDENT")
    ld_aggregation_method: Mapped[str] = mapped_column(String(20), nullable=False, server_default="SUM")
    ld_computation_base: Mapped[str] = mapped_column(String(30), nullable=False, server_default="QUARTERLY_PAYMENT")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Per-mapping variables the operator must fill in when attaching this
    # SLA to an activity. List of dicts with keys: key / label / type /
    # required / default_from / help. Empty list (default) means the SLA
    # plugs straight onto an activity without any per-mapping inputs.
    placeholders: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
    )
    # ── RFP-native presentation fields (UIDAI RFP §5.28 row headers) ──
    # category replaces formula_type for user-facing display; formula_type
    # stays on the row as the evaluator-dispatch key.
    category: Mapped[Optional[str]] = mapped_column(String(50))
    scope_text: Mapped[Optional[str]] = mapped_column(Text)
    data_source: Mapped[Optional[str]] = mapped_column(String(255))
    calculation_method: Mapped[Optional[str]] = mapped_column(Text)
    reports_submitted_to: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[Optional[date]] = mapped_column(Date)
    # ── Phase A additions (migration 0021) ──────────────────────────────
    # phase: RFP §5.28.2.a phase-gating classifier. Values:
    #   PHASE_1 (D1-D8 milestone deliverables),
    #   PHASE_2_3 (D9/D10 quarterly staff-cost SLAs),
    #   GOVERNANCE_TOOL (D11 annual),
    #   NONE (contract-wide, not tied to a phase).
    # NULL during rollout — Step 2 backfills.
    phase: Mapped[Optional[str]] = mapped_column(String(24))
    # RFP §5.28.3.f/g — SLA 008/009 carry severity across quarters until
    # onboarding lands. Rollup honours this by re-emitting the previous
    # quarter's severity into the current quarter's aggregate.
    carry_forward_severity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    # Which LD-arithmetic family this SLA uses. Full set from day one so
    # BSP/MSIP evaluators land without an ALTER TYPE — see plan tweak 1.
    # NULL during rollout means the current per-observation LD path is
    # used unchanged (backward-compatible).
    ld_formula_rule: Mapped[Optional[str]] = mapped_column(String(32))
    dsl_source: Mapped[Optional[str]] = mapped_column(Text)
    dsl_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
