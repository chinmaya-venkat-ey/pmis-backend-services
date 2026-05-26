"""ContractScoringConfig — severity→points and points→LD% mappings per contract.

Used by point_accumulation and wac formula types (MSAP, PMU contracts).
One row per contract (UNIQUE on contract_id).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContractScoringConfig(Base):
    __tablename__ = "contract_scoring_config"
    __table_args__ = (
        Index("ix_csc_contract_id", "contract_id", unique=True),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    severity_points_map: Mapped[dict] = mapped_column(JSONB, nullable=False)
    points_ld_map: Mapped[dict] = mapped_column(JSONB, nullable=False)
    applies_to_formulas: Mapped[list] = mapped_column(
        ARRAY(String(64)),
        nullable=False,
        default=lambda: ["point_accumulation", "wac"],
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
