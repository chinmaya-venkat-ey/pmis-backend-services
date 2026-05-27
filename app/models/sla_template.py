"""SlaTemplate — reusable SLA blueprint.

Stores a default DSL YAML and formula reference. Contract managers pick a
template when creating an SLA — the default_dsl is pre-filled and they override
only contract-specific values (effective_from, cap_percent, target_numeric, etc.).

Allows the same SLA pattern (e.g. "BSP Biometric Accuracy", "Key Resource Mobilization")
to be reused across contracts and project activities without re-entering all parameters.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaTemplate(Base):
    __tablename__ = "sla_templates"
    __table_args__ = (
        Index("ix_sla_templates_formula_id", "formula_id"),
        Index("ix_sla_templates_is_active", "is_active"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_ref: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    formula_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.formula_library.id"),
        nullable=False,
    )
    default_dsl: Mapped[str] = mapped_column(Text, nullable=False)
    # e.g. ["BSP", "MSAP", "PMU", "MSIP"] — which contract types this template applies to
    applicable_to: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
