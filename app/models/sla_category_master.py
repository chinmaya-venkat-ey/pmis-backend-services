"""SlaCategoryMaster — user-facing SLA category catalog.

Sibling of contract_type_master. Replaces the front-end's hardcoded
category-to-engine map. The FE shows ``display_name`` to the user; the BE
reads ``formula_type`` to dispatch the right evaluator.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaCategoryMaster(Base):
    __tablename__ = "sla_category_master"
    __table_args__ = (
        Index("ix_sla_category_master_sort_order", "sort_order"),
        CheckConstraint(
            "formula_type IN ('point_accumulation','fixed_escalation','band_accumulation','wac')",
            name="ck_sla_category_formula_type",
        ),
        {"schema": "contract"},
    )

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    formula_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
    )
