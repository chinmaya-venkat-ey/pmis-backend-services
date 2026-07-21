"""ProjectPhaseQrg — per-phase CONFIG row on the payment screen.

Originally a single ``qrg_applied`` flag; now the per-phase carry-forward
("carry forward cost", ex-QRG) config plus the phase ORDER:

  * ``sequence``              — integer phase order (restored after ``phase``
                               became a free-text string). Drives next/last
                               phase for carry-forward. NULL until assigned;
                               the service backfills from the numeric name.
  * ``carry_forward_enabled``— phase opts in to carrying its ENTIRE leftover
                               forward.
  * ``carry_forward_method_code``
                             — the master-driven carry-forward METHOD code
                               (``masters.carry_forward_methods.code``), e.g.
                               'phase_evenly' / 'milestone_evenly' /
                               'time_quarterly' / 'phase_custom'. The master row
                               carries the recipient unit (phase|milestone|time)
                               and the share ``formula``. NULL when disabled.
                               (Superseded the legacy 'phase'|'milestone'
                               ``carry_forward_mode`` flag, which maps onto the
                               ``*_evenly`` methods.)

Phase-wise carries compound down the chain (received grows a phase's base, so
its own onward leftover can include it). ``qrg_applied`` is retained (legacy)
but superseded by ``carry_forward_enabled``. One live row per (project, phase).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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


class ProjectPhaseQrg(Base):
    __tablename__ = "project_phase_qrg"
    __table_args__ = (
        Index("idx_phase_qrg_project_live", "project_id", "deleted_at"),
        Index(
            "uq_phase_qrg_project_phase_live",
            "project_id", "phase",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))
    phase: Mapped[str] = mapped_column(String(64))
    # Integer phase order (display name lives in ``phase``). NULL until set.
    sequence: Mapped[Optional[int]] = mapped_column(Integer)

    # Legacy QRG flag — kept for back-compat; superseded by carry_forward_enabled.
    qrg_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    # Carry-forward ("carry forward cost") config.
    carry_forward_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    # Master carry-forward method code when enabled (FK by value to
    # masters.carry_forward_methods.code). NULL when disabled.
    carry_forward_method_code: Mapped[Optional[str]] = mapped_column(String(40))

    # Per-phase share of the PROJECT one-time pool (opt-in). ``one_time_mode``
    # is 'percent' (of the one-time total) or 'amount' (₹). The chronologically
    # LAST phase auto-absorbs the unallocated remainder, so this config is only
    # honoured for non-last phases. NULL/false = the phase takes no explicit share.
    one_time_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    one_time_mode: Mapped[Optional[str]] = mapped_column(String(8))
    one_time_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    # Independent partial carry-forward percentages (bug #326). The one-time
    # (OPE) stream and the other-cost stream carry forward SEPARATELY instead of
    # as one clubbed leftover:
    #   * other_cost_carry_percent — % of this phase's OTHER-cost leftover
    #     (fixed/resource/transaction, unbilled by milestone %s) to carry via the
    #     carry-forward method. NULL → 100 when carry_forward_enabled (legacy
    #     "carry the whole leftover"), else 0.
    #   * one_time_carry_percent — % of this phase's OPE (allocation + carried-in)
    #     to carry forward phase-wise; the rest is retained in this phase's value
    #     and billed with it. NULL → 0 (OPE stays in the phase by default).
    other_cost_carry_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    one_time_carry_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
