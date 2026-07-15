"""DashboardMetricSnapshot — periodic point-in-time captures of dashboard
KPI values, used to derive the ``delta`` ("+6 vs last month") strings and
``spark`` (last-6-months) arrays the summary dashboard shows.

A row is one metric's value for one scope on one calendar date. The daily
snapshot job (``POST /api/v3/dashboard/cron/snapshot``, shared-secret
gated) writes the current values; the dashboard reads history back to
compute month-over-month deltas and sparklines.

Scope is generalised (``scope_type`` + ``scope_id``) so org- and
project-level series can be added later; today only ``global`` (scope_id
= "") is captured. ``scope_id`` is a NON-NULL empty string for global so
the uniqueness constraint behaves (Postgres treats NULLs as distinct).
"""
from __future__ import annotations

from datetime import date as _date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DashboardMetricSnapshot(Base):
    __tablename__ = "dashboard_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "captured_date", "scope_type", "scope_id", "metric_key",
            name="uq_dashboard_metric_snapshot",
        ),
        Index(
            "idx_dashboard_metric_snapshot_lookup",
            "metric_key", "scope_type", "scope_id", "captured_date",
        ),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    captured_date: Mapped[_date] = mapped_column(Date, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    metric_key: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
