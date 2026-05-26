"""SlaAslSnapshot — normalized ASL JSON produced by the DSL parser.

is_current=True marks the snapshot consumed by evaluation engines.
Only one snapshot per SLA should have is_current=True at any time.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaAslSnapshot(Base):
    __tablename__ = "sla_asl_snapshots"
    __table_args__ = (
        Index("ix_sla_asl_snapshots_sla_id", "sla_id"),
        Index("ix_sla_asl_snapshots_is_current", "is_current"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    dsl_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_dsl_versions.id"),
        nullable=False,
    )
    asl_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
