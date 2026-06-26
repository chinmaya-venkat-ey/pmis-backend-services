"""ProjectPhaseQrg — per-phase CONFIG row on the payment screen.

Originally a single ``qrg_applied`` flag; now the per-phase carry-forward
("carry forward cost", ex-QRG) config plus the phase ORDER:

  * ``sequence``              — integer phase order (restored after ``phase``
                               became a free-text string). Drives next/last
                               phase for carry-forward. NULL until assigned;
                               the service backfills from the numeric name.
  * ``carry_forward_enabled``— phase opts in to carrying its ENTIRE leftover
                               forward.
  * ``carry_forward_mode``   — the distribution unit: 'phase' (split the
                               leftover equally across all SUBSEQUENT phases'
                               totals) or 'milestone' (split equally across all
                               subsequent milestones' payable values). NULL when
                               disabled.

Phase-wise carries compound down the chain (received grows a phase's base, so
its own onward leftover can include it). ``qrg_applied`` is retained (legacy)
but superseded by ``carry_forward_enabled``. One live row per (project, phase).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
    # Distribution unit when enabled: 'phase' | 'milestone'.
    carry_forward_mode: Mapped[Optional[str]] = mapped_column(String(16))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
