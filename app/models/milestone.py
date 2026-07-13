"""Milestone SQLAlchemy model — owned by pmis-project-management.

Per-project position is unique among LIVE rows (partial unique index where
`deleted_at IS NULL`). Drives the M{n} display label.

`priority` is a logical FK to `masters.priorities.code` (cross-schema).
`status` is a logical FK to `masters.milestone_statuses.code`.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        Index("idx_milestones_project_live", "project_id", "deleted_at"),
        Index("idx_milestones_project_position", "project_id", "position"),
        Index(
            "uq_milestones_project_position_live",
            "project_id", "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_milestones_status", "status"),
        Index("ix_milestones_priority", "priority"),
        Index("ix_milestones_payment_type", "payment_type"),
        Index("ix_milestones_deleted_at", "deleted_at"),
        {"schema": "project"},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("project.projects.id"),
    )

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="not_completed")
    priority: Mapped[Optional[str]] = mapped_column(String(16))
    # Logical FK to masters.payment_types.code (cross-schema). Nullable.
    payment_type: Mapped[Optional[str]] = mapped_column(String(32))

    # Category + CCN value (Doc-finance).
    #   'original' — created pre-publish; the entire baseline scope (default).
    #   'asg'      — Annual Strategic Goal (post-publish addition, no money).
    #   'ccn'      — Change Control Note (post-publish addition, carries
    #                ``ccn_value`` consumed against the project CCN cap).
    # Pre-publish creates always store 'original'; the category dropdown
    # only appears on post-publish create (FE-driven; the BE enforces the
    # transition). DB CHECK constraints (see migration p1a000000006) keep
    # category restricted to the three known codes and force ccn_value=0
    # when category != 'ccn'.
    category: Mapped[str] = mapped_column(
        String(16), nullable=False,
        server_default=text("'original'"), default="original",
    )
    ccn_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False,
        server_default=text("0"), default=Decimal("0"),
    )

    # 2026-06-03: meeting-milestone flag. When TRUE, this milestone is
    # auto-managed by the publish flow and acts as a container for
    # meeting-type activities. It is filtered out of every milestone-
    # level surface (list endpoints, dashboards, critical path, discussion
    # feed) and is not directly editable or deletable via API. The single
    # project_response field ``meetingMilestoneId`` exposes its id so the
    # FE can create activities under it. A partial unique index
    # (see migration p1a000000007_is_meeting) enforces at most one live
    # meeting milestone per project.
    is_meeting: Mapped[bool] = mapped_column(
        Boolean, nullable=False,
        server_default=text("false"), default=False,
    )

    # Delivery-model flags (see migration p1a000000027). ``is_resource_based``
    # marks the milestone as resource/man-month driven; ``is_transaction_based``
    # marks it as per-transaction driven. Both are non-nullable booleans that
    # default to false. On the wire ``isResourceBased`` is mandatory (client must
    # send it on create) and ``isTransactionBased`` is optional.
    is_resource_based: Mapped[bool] = mapped_column(
        Boolean, nullable=False,
        server_default=text("false"), default=False,
    )
    is_transaction_based: Mapped[bool] = mapped_column(
        Boolean, nullable=False,
        server_default=text("false"), default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
