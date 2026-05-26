"""ContractPhase — named phase within a contract lifecycle.

Examples: Transition and Takeover, Development and Maintenance, Operations.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContractPhase(Base):
    __tablename__ = "contract_phases"
    __table_args__ = (
        Index("ix_contract_phases_contract_id", "contract_id"),
        Index("ix_contract_phases_is_active", "is_active"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
