"""SlaDefinition — one row per SLA within a project.

Roots at project_ld_config.project_id (within contract schema).
All formula parameters, metrics, bands, and lookup tables hang off this row via FKs.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaDefinition(Base):
    __tablename__ = "sla_definitions"
    __table_args__ = (
        Index("ix_sla_def_project_id", "project_id"),
        Index("ix_sla_def_project_sla_ref", "project_id", "sla_ref", unique=True),
        Index("ix_sla_def_formula_id", "formula_id"),
        Index("ix_sla_def_status", "status"),
        # G25 soft-FK indexes
        Index("ix_sla_def_activity_id", "activity_id"),
        Index("ix_sla_def_milestone_id", "milestone_id"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    # Root anchor: FK to project_ld_config.project_id (within contract schema)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.project_ld_config.project_id", ondelete="CASCADE"),
        nullable=False,
    )

    # G25: soft cross-service references to project module (no DB FK — cross-service)
    activity_id: Mapped[Optional[str]] = mapped_column(String(36))
    milestone_id: Mapped[Optional[str]] = mapped_column(String(36))

    formula_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.formula_library.id"),
        nullable=False,
    )

    sla_ref: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    measurement_interval: Mapped[str] = mapped_column(String(30), nullable=False, default="MONTHLY")
    reporting_interval: Mapped[str] = mapped_column(String(30), nullable=False, default="QUARTERLY")
    baseline_type: Mapped[str] = mapped_column(String(30), nullable=False, default="STATIC")
    compound_metric_rule: Mapped[str] = mapped_column(String(30), nullable=False, default="INDEPENDENT")
    ld_aggregation_method: Mapped[str] = mapped_column(String(20), nullable=False, default="SUM")
    ld_computation_base: Mapped[str] = mapped_column(String(30), nullable=False, default="QUARTERLY_PAYMENT")

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[Optional[date]] = mapped_column(Date)

    dsl_source: Mapped[Optional[str]] = mapped_column(Text)
    dsl_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
