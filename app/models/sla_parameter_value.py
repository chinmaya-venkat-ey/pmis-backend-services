"""SlaParameterValue — formula-specific key-value parameters per SLA."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaParameterValue(Base):
    __tablename__ = "sla_parameter_values"
    __table_args__ = (
        Index("ix_sla_param_values_sla_id", "sla_id"),
        UniqueConstraint("sla_id", "param_key", name="uq_sla_param_values_sla_key"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    sla_id: Mapped[str] = mapped_column(String(36), nullable=False)
    param_key: Mapped[str] = mapped_column(String(100), nullable=False)
    param_value: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
