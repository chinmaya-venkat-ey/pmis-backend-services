"""ActivityPlannedResource — one planned-resource allocation row on an activity.

A **resource-based** activity (one under a milestone with ``is_resource_based``)
carries a 1:many set of allocation rows: how many of a given ``designation`` are
deployed on it, and for how long (``duration``, in months). Designation NAMES and
their per-contract-year rates live in the Java leave-management module
(``/api/designation-rates``). At create/edit time the monthly rate is resolved from
that service (for the activity's contract year) and **snapshotted** here alongside
the derived ``computed_cost`` = ``quantity × monthly_rate × duration``, so reads
and the finance page never call the Java service and a later master-rate change
does not restate saved allocations. An activity's resource cost is the sum of its
rows, which surfaces on the finance page as the activity's value in a resource-based
(partial-payment) milestone's activity-wise breakup.

``designation`` is the free-text ``role`` string as returned by the Java service
(NOT an FK). ``duration`` is a flat number of months in ``[0, 3]`` (an activity
corresponds to one quarter) with 2-dp precision — no deployment dates.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActivityPlannedResource(Base):
    __tablename__ = "activity_planned_resources"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="ck_activity_planned_res_qty_positive"),
        CheckConstraint(
            "duration >= 0 AND duration <= 3",
            name="ck_activity_planned_res_duration_range",
        ),
        Index("idx_activity_planned_res_activity_live", "activity_id", "deleted_at"),
        Index("idx_activity_planned_res_project_live", "project_id", "deleted_at"),
        Index("ix_activity_planned_res_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    activity_id: Mapped[str] = mapped_column(ForeignKey("project.activities.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("project.projects.id"))

    # The designation NAME (the Java service's ``role`` string; free text, NOT an FK).
    designation: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    # Flat number of months in [0, 3] (2dp) — no deployment dates.
    duration: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    # SNAPSHOT of the monthly rate resolved from the Java designation-rates service
    # at create/edit time (for the activity's contract year), and the derived cost
    # = quantity × monthly_rate × duration. Stored so reads + finance never call the
    # Java service; a later master-rate change does not restate saved allocations.
    monthly_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    computed_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    position: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
