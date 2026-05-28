"""SeverityMaster — per-project severity level definitions.

One row per level (0-4) per project. Seeded automatically when a
project_ld_config is created via ProjectLdConfigService.create().
Points can be negative (level 0 = exceptional performance = -2 pts by default).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SeverityMaster(Base):
    __tablename__ = "severity_master"
    __table_args__ = (
        Index("ix_sev_master_project_id", "project_id"),
        UniqueConstraint("project_id", "level", name="uq_sev_master_project_level"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)   # 0-4
    points: Mapped[int] = mapped_column(Integer, nullable=False)  # negative allowed
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
