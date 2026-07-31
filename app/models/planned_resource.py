"""PlannedResource — one planned-resource row on a resource-type phase.

Rows belong to a ``resource_cost`` cost item (``cost_item_id``) — the phase's
resource cost row. Each row plans a headcount of a designation (``role``) over a
deployment window, priced from the **per-contract-year rate card** the client
supplies (sourced from the leave-management ``/api/designation-rates`` service).
The cost is split by contract year: for each year the window spans,
``quantity × rateCardByYear["Year-N"] × months-in-that-year`` (fractional months,
days / 30.44), summed into ``computed_cost``; the per-year split is kept in
``cost_by_year``. The SUM of a cost row's live planned-resource costs is written
back onto that cost item's ``cost`` (so the existing payment/carry-forward math is
untouched). Multiple rows may share a role (e.g. several architects for different
windows); they all accumulate into the SUM.

``role`` is the designation NAME (free text, as leave-mgmt returns it — not an FK).
``vendor_id`` is the organisation (masters.vendors.id) the rate card belongs to.
``rate_card_snapshot`` snapshots the ``rateCardByYear`` map at entry so later
rate-card edits don't silently restate historical plans.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PlannedResource(Base):
    __tablename__ = "planned_resources"
    __table_args__ = (
        Index("idx_planned_res_project_live", "project_id", "deleted_at"),
        Index("idx_planned_res_cost_item_live", "cost_item_id", "deleted_at"),
        Index(
            "uq_planned_res_project_position_live",
            "project_id", "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_planned_res_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))
    # The resource_cost cost row this planned resource rolls up into.
    cost_item_id: Mapped[str] = mapped_column(
        ForeignKey("project.project_cost_items.id")
    )
    # The designation NAME (free text, as leave-mgmt returns it — not an FK) and
    # the organisation (masters.vendors.id) whose rate card this row uses.
    role: Mapped[Optional[str]] = mapped_column(String(255))
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))

    quantity: Mapped[int] = mapped_column(Integer, default=1)
    deploy_start: Mapped[Optional[date]] = mapped_column(Date)
    deploy_end: Mapped[Optional[date]] = mapped_column(Date)

    # Snapshot of the client-supplied rateCardByYear map {"Year-N": monthlyRate}.
    rate_card_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    # Per-contract-year cost breakdown {"Year-N": amount} (transparency).
    cost_by_year: Mapped[Optional[dict]] = mapped_column(JSONB)
    # Total deployment window in fractional months (Σ per-year months).
    duration_months: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    computed_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    position: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
