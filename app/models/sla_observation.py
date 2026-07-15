"""SlaObservation — the latest observed value for one SLA mapping.

The SLA engine judges an *observed value* (days delayed, a %, a count, a
defect breakdown). Historically the caller passed that value on every
evaluate request and it was discarded. For the daily automated evaluation
we must persist it: this table is the standing record of "what was
observed" per mapping, fed two ways —

  * ``source = 'auto'``     — the daily cron derives it from the activity's
                              dates (deadline / duration SLAs only).
  * ``source = 'recorded'`` — supplied through the observation-input API
                              for the SLAs whose value can't come from
                              dates (retention %, counts, KT-overlap days,
                              WAC defect breakdowns, …).

``observed_value`` is JSONB so it can hold whatever the engine's formula
needs: a bare number (fixed_escalation / point_accumulation), a list
(band_accumulation daily values), or an object (BAND_COUNTS / WAC).

Rows are period-scoped (``period_start`` / ``period_end``) because SLAs are
measured per interval (usually quarterly). The cron reads the most recent
observation whose period covers the run.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SlaObservation(Base):
    __tablename__ = "sla_observations"
    __table_args__ = (
        Index("ix_sla_obs_mapping", "mapping_id"),
        Index("ix_sla_obs_project", "project_id"),
        Index("ix_sla_obs_activity", "activity_id"),
        Index("ix_sla_obs_mapping_period", "mapping_id", "period_end"),
        {"schema": "contract"},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    mapping_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("contract.sla_activity_mappings.id", ondelete="CASCADE",
                   name="fk_sla_obs_mapping"),
        nullable=False,
    )
    # Denormalised for aggregate queries (soft FKs — Activity/Project are
    # owned by project-management).
    sla_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[Optional[str]] = mapped_column(String(36))

    # Null = a value for the whole SLA (single-metric case); otherwise the
    # specific metric this observation is for.
    metric_key: Mapped[Optional[str]] = mapped_column(String(120))

    # The observed value, shape per formula: number | list | object.
    observed_value: Mapped[Any] = mapped_column(JSONB, nullable=False)

    # 'auto' (derived from activity dates) | 'recorded' (input API).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="recorded")

    period_start: Mapped[Optional[date]] = mapped_column(Date)
    period_end: Mapped[Optional[date]] = mapped_column(Date)

    note: Mapped[Optional[str]] = mapped_column(Text)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(36))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=datetime.utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False,
    )
