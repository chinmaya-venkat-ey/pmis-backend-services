"""ProjectPhaseQrg — per-phase CONFIG row on the payment screen.

Originally a single ``qrg_applied`` flag; now the per-phase carry-forward
("carry forward cost", ex-QRG) config plus the phase ORDER:

  * ``sequence``              — integer phase order (restored after ``phase``
                               became a free-text string). Drives next/last
                               phase for carry-forward. NULL until assigned;
                               the service backfills from the numeric name.
  * ``carry_forward_enabled``— phase opts in to carrying its leftover forward.
  * ``carry_forward_mode``   — 'percent' (of the phase's remaining/leftover)
                               or 'amount' (a flat figure). NULL when disabled.
  * ``carry_forward_percent``/``carry_forward_amount`` — exactly one is set
                               when enabled; the other is NULL.

Carry-forward flows to the IMMEDIATE NEXT phase only (by ``sequence``) and
compounds down the chain. ``qrg_applied`` is retained (legacy / back-compat)
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
    carry_forward_mode: Mapped[Optional[str]] = mapped_column(String(16))
    carry_forward_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    carry_forward_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
