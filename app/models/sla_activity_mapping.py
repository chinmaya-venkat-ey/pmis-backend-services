"""SlaActivityMapping — binds an SLA master to an external Activity.

Activity is owned by PMIS-Project-management. We store only `activity_id`
(soft FK). The `overrides` JSONB carries instance-specific values that take
precedence over the SLA master at evaluation time. Well-known keys are
declared on the SLA template's ``placeholders`` array (see
`sla_definitions.placeholders` added in migration 0016). Examples:

  - t_anchor_date         (concrete date for the SLA's symbolic T anchor)
  - actual_start_date     (real period start; overrides effective_from)
  - actual_end_date       (real period end)
  - ld_base_amount        (INR base for LD calc on this activity)
  - severity_profile_id   (override project's severity profile, if any)

The list is intentionally open — new keys are added as requirements emerge,
without a schema migration.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaActivityMapping(Base):
    __tablename__ = "sla_activity_mappings"
    __table_args__ = (
        Index("ix_sam_activity_id", "activity_id"),
        Index("ix_sam_sla_id", "sla_id"),
        Index("ix_sam_status", "status"),
        UniqueConstraint(
            "activity_id", "sla_id", "effective_from",
            name="uq_sam_activity_sla_effective",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','INACTIVE','RETIRED')",
            name="ck_sam_status",
        ),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sla_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_definitions.id", ondelete="RESTRICT", name="fk_sam_sla_id"),
        nullable=False,
    )
    overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[Optional[date]] = mapped_column(Date)
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
    )
