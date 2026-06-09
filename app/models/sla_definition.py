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
    dsl_source: Mapped[Optional[str]] = mapped_column(Text)
    dsl_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
