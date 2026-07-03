"""ProjectCfPoolInstallment — a dated installment of a FREQUENCY-based carry.

When a phase carries its leftover forward by a frequency method (monthly /
quarterly / half-yearly / yearly), the money is NEVER added to any phase or
milestone value (see the payment contract's "golden rule"). It becomes a pool of
dated installments — one row per calendar period after the carrying phase ends,
up to the project end — that invoicing later draws from.

  * ``source_phase``    — the carrying phase (matches ``project_phase_qrg.phase``).
  * ``frequency_code``  — the method's calendar frequency (the bucket size).
  * ``period_index``    — the monotonic calendar-bucket index (see cycle_calc).
  * ``period_start/end``— that bucket's calendar span.
  * ``amount``          — the installment value (Σ over a phase = its leftover).
  * ``status``          — 'pending' (default) or 'on_invoice' once an invoice has
                          drawn it (invoicing, to be built, sets this + invoice_ref;
                          once on_invoice the carry can no longer be changed).

NOTE: the payment page recomputes the schedule fresh on every read (authoritative);
these rows are the durable snapshot written when carry-forward is configured, for
the forthcoming invoicing screen to consume/freeze. Soft-deleted via ``deleted_at``;
the service replaces the whole pending set for a phase on each save. One live row
per (project, source_phase, period_index).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Date,
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


class ProjectCfPoolInstallment(Base):
    __tablename__ = "project_cf_pool_installment"
    __table_args__ = (
        Index("idx_cf_pool_project_live", "project_id", "deleted_at"),
        Index(
            "uq_cf_pool_live",
            "project_id", "source_phase", "period_index",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))
    source_phase: Mapped[str] = mapped_column(String(64))
    frequency_code: Mapped[str] = mapped_column(String(16))
    period_index: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    invoice_ref: Mapped[Optional[str]] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
