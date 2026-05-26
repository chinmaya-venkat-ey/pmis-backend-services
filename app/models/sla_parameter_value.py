"""SlaParameterValue — formula parameter key-value pairs for an SLA.

param_key must match a key in formula_library.parameter_schema.
param_value is always stored as text; the evaluation engine casts it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaParameterValue(Base):
    __tablename__ = "sla_parameter_values"
    __table_args__ = (
        Index("ix_sla_param_values_sla_id", "sla_id"),
        Index("ix_sla_param_values_sla_key", "sla_id", "param_key", unique=True),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    param_key: Mapped[str] = mapped_column(String(100), nullable=False)
    param_value: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
