"""Designation catalog — owned by pmis-masters-management.

A simple lookup of job designations (e.g. "Consultant"). Same shape as the
other simple masters (resource_types etc.).

**Soft-delete model:** ``active=False`` (no ``deleted_at`` column — only vendors
keeps the deleted_at/deleted_by audit pattern).

**Per-organization + rate:** a designation is scoped to an organization
(``vendor_id`` → masters.vendors.id) and carries a ``monthly_rate`` used to cost
planned resources (monthly_rate × months × quantity). Each org may have its own
designations/rates, so uniqueness is ``(vendor_id, code)`` rather than global.
``vendor_id`` NULL = a global/template row (e.g. the seeded "consultant").
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Designation(Base):
    __tablename__ = "designations"
    __table_args__ = (
        # Uniqueness is per organization: the same code may exist once per vendor.
        Index("ix_designations_vendor_code", "vendor_id", "code", unique=True),
        Index("ix_designations_vendor_id", "vendor_id"),
        Index("ix_designations_active", "active"),
        {"schema": "masters"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    # Logical FK to masters.vendors.id (the "Organization"). NULL = global row.
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))
    # Per-month rate for this org's designation; drives planned-resource costing.
    monthly_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
