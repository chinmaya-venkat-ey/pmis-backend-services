"""ProjectLdBand — per-project points-to-LD% chart.

Sibling of SeverityMaster. Where severity_master maps a project's severity
level to scoring points, project_ld_bands maps the *accumulated* points to
an LD percentage. Together they let a project fully override the RFP
defaults baked into the evaluator.

Multiple rows per project. The evaluator walks them ascending by
points_threshold and uses the highest tier the accumulated points meet —
same semantics as the in-code ``DEFAULT_POINTS_TO_LD`` fallback in
``point_accumulation.py``.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectLdBand(Base):
    __tablename__ = "project_ld_bands"
    __table_args__ = (
        Index("ix_pldb_project_id", "project_id"),
        UniqueConstraint("project_id", "points_threshold", name="uq_pldb_project_threshold"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    points_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    ld_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
