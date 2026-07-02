"""ProjectCostItem — a row of the Project-Finance "Project Cost" table.

Each row carries a ``cost_type_code`` (logical FK to masters.cost_types.code,
e.g. 'fixed' / 'one_time'), an optional ``cost`` (excl-tax amount) and
``tax_percent``; the inclusive ``total`` is derived on response, never
stored.

  * ``fixed``    rows belong to a ``phase`` (free integer 1,2,3…) and bind a
                 bundle of milestones via ``cost_item_milestones``. The single
                 ``cost`` covers the whole bundle.
  * ``one_time`` rows are a single deliverable — no phase, no milestones.
                 At most ONE live one-time row per project (partial unique
                 index ``uq_cost_items_one_time_per_project_live``).

Per-project ``position`` is unique among LIVE rows (partial unique index
where ``deleted_at IS NULL``). Fields are intentionally nullable for now
(mandatory rules land later, per requirement).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectCostItem(Base):
    __tablename__ = "project_cost_items"
    __table_args__ = (
        Index("idx_cost_items_project_live", "project_id", "deleted_at"),
        Index("idx_cost_items_project_position", "project_id", "position"),
        Index(
            "uq_cost_items_project_position_live",
            "project_id", "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # At most one live one-time cost row per project.
        Index(
            "uq_cost_items_one_time_per_project_live",
            "project_id",
            unique=True,
            postgresql_where=text("cost_type_code = 'one_time' AND deleted_at IS NULL"),
        ),
        Index("ix_cost_items_cost_type_code", "cost_type_code"),
        Index("ix_cost_items_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))

    # Logical FK to masters.cost_types.code (cross-schema). Nullable for now.
    cost_type_code: Mapped[Optional[str]] = mapped_column(String(32))
    # Free-text phase label (e.g. "1", "Phase A"). NULL for one-time rows.
    phase: Mapped[Optional[str]] = mapped_column(String(64))

    cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    # Tax is now an exact AMOUNT (e.g. 1000 on a 10000 cost). ``total`` =
    # cost + tax_amount. ``tax_percent`` is the legacy column, kept (optional)
    # but no longer used in calculations.
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    tax_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    # Transaction-cost rows: total = per_transaction_cost × planned_transactions.
    per_transaction_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    planned_transactions: Mapped[Optional[int]] = mapped_column(Integer)
    # Display label for a standalone expense line (resource / transaction cost) —
    # the "milestone" name for that cost. NULL for fixed / one-time rows.
    line_label: Mapped[Optional[str]] = mapped_column(String(255))
    # How much of a resource/transaction line's own value is BILLED in its phase.
    # ``billed_mode`` = 'percent' (of the line's value) | 'amount' (₹); default
    # percent 100 (fully billed). Whatever is not billed carries forward with the
    # phase's leftover. NULL for fixed / one-time rows.
    billed_mode: Mapped[Optional[str]] = mapped_column(String(8))
    billed_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

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
