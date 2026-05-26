"""SlaDslVersion — audit log of DSL YAML text for an SLA.

Each change to an SLA's DSL increments the version. The parser converts
the latest version to an ASL snapshot stored in sla_asl_snapshots.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaDslVersion(Base):
    __tablename__ = "sla_dsl_versions"
    __table_args__ = (
        Index("ix_sla_dsl_versions_sla_id", "sla_id"),
        Index("ix_sla_dsl_versions_sla_version", "sla_id", "version", unique=True),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    dsl_text: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[Optional[str]] = mapped_column(Text)
    authored_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
