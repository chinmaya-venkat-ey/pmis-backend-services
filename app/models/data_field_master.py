"""DataFieldMaster — observable variable catalog for the SLA condition builder.

Seeded at migration time with ~22 fields covering MSAP SLA 001-027 and
common BSP / PMU / MSIP / GRCP scenarios.

field_name    : snake_case internal key used in DSL expressions
display_name  : human-readable label shown to the admin in the onboarding form
data_type     : INTEGER | DECIMAL | DATE | BOOLEAN
unit          : %, days, hours, count, score, ms
applicable_to : NULL = field is available for all contract types;
                non-NULL = only shown when the selected contract type is in the list
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DataFieldMaster(Base):
    __tablename__ = "data_field_master"
    __table_args__ = {"schema": "contract"}

    field_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    example_value: Mapped[Optional[str]] = mapped_column(String(50))
    applicable_to: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String(20)))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
