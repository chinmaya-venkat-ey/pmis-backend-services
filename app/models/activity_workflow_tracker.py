"""ActivityWorkflowTracker — mirrors the latest known state of an activity's
approval workflow that lives in the separate Java workflow service.

The Java service owns the canonical state machine. This table is a fast-
lookup cache so the Approval Inbox listing doesn't need N round-trips to
Java to enumerate which activities are pending for a given role.

Lifecycle:
  - INSERT on first SUBMIT (proxied through ``services.workflow_client``).
  - UPDATE on every subsequent ``_transition`` call — ``current_state`` and
    ``last_synced_at`` get refreshed.
  - The inbox service may also re-sync ``current_state`` from Java's
    ``_search`` on read when ``last_synced_at`` is older than a threshold.

``business_id`` is the activity UUID (no separate scheme).
``consent_divisions`` and ``owner_division`` are snapshotted at SUBMIT
time so the inbox routing rules don't shift when the activity is later
edited.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActivityWorkflowTracker(Base):
    __tablename__ = "activity_workflow_tracker"
    __table_args__ = (
        Index("idx_activity_workflow_tracker_state_live", "current_state", "deleted_at"),
        Index("idx_activity_workflow_tracker_owner_div", "owner_division"),
        Index("idx_activity_workflow_tracker_project", "project_id"),
        Index("idx_activity_workflow_tracker_activity", "activity_id"),
        {"schema": "project"},
    )

    business_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    activity_id: Mapped[str] = mapped_column(ForeignKey("project.activities.id"))
    project_id: Mapped[str] = mapped_column(String(36))

    process_instance_id: Mapped[Optional[str]] = mapped_column(String(64))
    current_state: Mapped[str] = mapped_column(String(64))

    consent_divisions: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    owner_division: Mapped[Optional[str]] = mapped_column(String(64))
    vendor_id: Mapped[Optional[str]] = mapped_column(String(36))

    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36))
    updated_by: Mapped[Optional[str]] = mapped_column(String(36))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[str]] = mapped_column(String(36))
