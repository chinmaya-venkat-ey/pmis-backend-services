"""ProjectQgrConfig — per-project × phase QGR value.

Replaces the legacy ``project_phase_qrg`` stub (whose ``qrg_applied``
flag was documented as superseded — see its own docstring). Additive:
the stub is left in place until nothing reads it.

RFP §5.23.2 defines QGR as a Phase-1 concept. NpqpService reads a row
here only when the phase's ``contract_phase_config.qgr_eligible = true``
(i.e. PMU Phase 1). MSAP projects will have zero rows here — clean.

``effective_from`` / ``effective_until`` lets QGR change quarter-over-
quarter without dropping history.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Date, DateTime, Index, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectQgrConfig(Base):
    __tablename__ = "project_qgr_config"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "phase", "effective_from",
            name="uq_qgr_project_phase_from",
        ),
        Index("ix_qgr_project_phase", "project_id", "phase"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    qgr_amount_per_quarter: Mapped[Decimal] = mapped_column(NUMERIC(18, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
