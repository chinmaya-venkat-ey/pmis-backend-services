"""ProjectPhaseCfAllocation — per-recipient CUSTOM carry-forward split.

When a phase carries forward with a ``*_custom`` method, its entire leftover is
split across recipients by an EXPLICIT per-recipient share instead of evenly.
Each row is one recipient's share of one carrying phase's leftover:

  * ``source_phase``   — the carrying phase (matches ``project_phase_qrg.phase``).
  * ``recipient_kind`` — 'phase' (phase_custom; recipient_key is a phase name) or
                         'milestone' (milestone_custom; recipient_key is a
                         milestone id).
  * ``recipient_key``  — the subsequent phase name / milestone id receiving a share.
  * ``alloc_mode``     — how the user entered the share: 'percent' (0..100 of the
                         leftover) or 'amount' (rupees). The FE radio.
  * ``input_value``    — the raw entered percent / amount (kept for round-trip).
  * ``percent``        — the NORMALISED share (0..100). For 'percent' rows this
                         equals input_value; for 'amount' rows it is
                         input_value / leftover × 100 computed at save time. The
                         distribution engine feeds this as ``recipientPercent``
                         into the master formula. Shares for one ``source_phase``
                         must sum to 100 ("must fully allocate"); some may be 0.

Soft-deleted via ``deleted_at``; the service replaces the whole set for a phase
on each save. One live row per (project, source_phase, recipient_key).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectPhaseCfAllocation(Base):
    __tablename__ = "project_phase_cf_allocation"
    __table_args__ = (
        Index("idx_phase_cf_alloc_project_live", "project_id", "deleted_at"),
        Index(
            "uq_phase_cf_alloc_live",
            "project_id", "source_phase", "recipient_key",
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
    recipient_kind: Mapped[str] = mapped_column(String(16))
    recipient_key: Mapped[str] = mapped_column(String(64))
    alloc_mode: Mapped[str] = mapped_column(String(8))
    input_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 2))
    percent: Mapped[Optional[float]] = mapped_column(Numeric(9, 4))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
