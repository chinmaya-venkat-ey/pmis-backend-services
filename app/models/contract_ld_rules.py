"""ContractLdRules — per-contract LD parameters (data-driven).

Reason: the 4 RFPs have different per-week / per-day / cap numbers baked
into their SLA prose. Storing them as rows keeps the code the same across
contracts — the settlement service reads the rule for the row's contract
type at evaluation time.

Seed examples (Step 2 for PMU, later migrations for BSP/MSAP/MSIP):

  PMU  sla_001_rate_pct_per_week   0.5   PERCENT
  PMU  sla_002_rate_pct_per_week   1.0   PERCENT
  PMU  sla_003_rate_pct_per_day    0.1   PERCENT
  PMU  quarterly_ld_cap_pct       10.0   PERCENT
  MSAP quarterly_ld_cap_pct       10.0   PERCENT
  MSAP ccn_join_quarter_exempt     1     BOOL   (encoded as 1/0 numeric)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ContractLdRules(Base):
    __tablename__ = "contract_ld_rules"
    __table_args__ = (
        UniqueConstraint(
            "contract_type", "rule_key",
            name="uq_contract_ld_rules",
        ),
        Index("ix_contract_ld_rules_type", "contract_type"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_value: Mapped[Decimal] = mapped_column(NUMERIC(12, 4), nullable=False)
    # 'PERCENT' | 'DAYS' | 'WEEKS' | 'INR' | 'BOOL'
    unit: Mapped[Optional[str]] = mapped_column(String(16))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False,
    )
