"""ProjectPhaseQrg — per-phase "QRG Applied" flag on the payment screen.

QRG is asked once per phase (not per milestone). Only the boolean is
stored; the QRG value / percent are derived on response:

    qrg_value   = phase fixed total − Σ(payment-term values in the phase)
    qrg_percent = 100 − Σ(percent_of_payment in the phase)

One live row per (project, phase).
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
    phase: Mapped[int] = mapped_column(Integer)
    qrg_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
