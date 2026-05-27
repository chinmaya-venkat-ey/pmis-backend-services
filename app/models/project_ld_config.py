"""ProjectLdConfig — LD financial terms for a project.

One row per project. project_id is a soft cross-service FK to project.projects.id.
Holds only what the project module does NOT have: contract reference number,
financial value, quarterly LD cap, and MSAP/PMU scoring config.

ld_status is the LD lifecycle (separate from project status):
  ACTIVE | PROBATION | SUSPENDED | EXPIRED | TERMINATED
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectLdConfig(Base):
    __tablename__ = "project_ld_config"
    __table_args__ = (
        Index("ix_plc_project_id", "project_id", unique=True),
        Index("ix_plc_contract_ref", "contract_ref", unique=True),
        Index("ix_plc_ld_status", "ld_status"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # Soft cross-service FK — project.projects.id (no DB constraint)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    contract_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    total_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'INR'"))
    quarterly_ld_cap_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    ld_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ACTIVE'"))

    # MSAP/PMU scoring config — NULL for BSP/MSIP
    severity_points_map: Mapped[Optional[list]] = mapped_column(JSONB)
    points_ld_map: Mapped[Optional[list]] = mapped_column(JSONB)
    scoring_applies_to: Mapped[Optional[list]] = mapped_column(ARRAY(String(64)))

    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'")
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
