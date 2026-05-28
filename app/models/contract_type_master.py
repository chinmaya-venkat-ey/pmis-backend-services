"""ContractTypeMaster — system-wide contract type reference data.

Seeded at migration time with: BSP, MSAP, PMU, MSIP, GRCP.
Used by the SLA onboarding form to filter applicable data fields and templates.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContractTypeMaster(Base):
    __tablename__ = "contract_type_master"
    __table_args__ = {"schema": "contract"}

    code: Mapped[str] = mapped_column(String(20), primary_key=True)   # BSP, MSAP, …
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
