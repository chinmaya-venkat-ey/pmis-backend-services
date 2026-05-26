"""FormulaLibrary — master catalogue of SLA formula types.

One row per formula type (band_accumulation, point_accumulation,
fixed_escalation, wac). Seeded at migration time; never edited via API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FormulaLibrary(Base):
    __tablename__ = "formula_library"
    __table_args__ = (
        Index("ix_formula_library_formula_type", "formula_type", unique=True),
        Index("ix_formula_library_is_active", "is_active"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    formula_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    parameter_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requires_bands: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_lookup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
