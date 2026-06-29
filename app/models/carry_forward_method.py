"""Carry-forward methods catalog — owned by pmis-masters-management.

Drives the Project-Finance carry-forward "method" selector. Each row is a
(method, variant) combination plus a configurable ``formula`` used to compute
the per-recipient carry-forward amount — so new distribution variants are
CONFIG, not code.

  method:  'milestone' | 'phase' | 'time'
  variant: 'evenly' | 'custom' | 'monthly' | 'quarterly' | 'half_yearly' | 'yearly'
  formula: an arithmetic expression over a fixed variable set
           (leftover, numRecipients, recipientCycles, totalCycles, recipientPercent).

Same simple-deactivate model as cost_types / payment_types (active=False,
no deleted_at). Codes are lowercase snake.

WARNING: Mirrored in
services/pmis-project-management/app/models/_cross_schema.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CarryForwardMethod(Base):
    __tablename__ = "carry_forward_methods"
    __table_args__ = (
        Index("ix_carry_forward_methods_code", "code", unique=True),
        Index("ix_carry_forward_methods_active", "active"),
        Index("idx_carry_forward_methods_active_code", "active", "code"),
        {"schema": "masters"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    method: Mapped[str] = mapped_column(String(16))      # milestone | phase | time
    variant: Mapped[str] = mapped_column(String(16))     # evenly | custom | monthly | ...
    formula: Mapped[str] = mapped_column(String(500))    # arithmetic expression
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
