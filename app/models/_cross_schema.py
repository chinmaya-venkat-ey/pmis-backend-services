"""Read-only cross-schema mirrors of tables owned by other services.

Declared on ``MirrorBase`` (NOT ``Base``) so they are excluded from this
service's Alembic metadata — we never create or migrate them, we only read
them. Same pattern the other PMIS services use (see notification-svc's
``_cross_schema.py``).

Why: the SLA compliance cron must resolve an activity's project / milestone
/ planned + actual dates. Rather than call project-management over HTTP with
a service token (which a daily job can't easily hold), it reads
``project.activities`` directly from the shared database — so the cron needs
only its shared secret, no bearer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import MirrorBase


class Activity(MirrorBase):
    """Mirror of ``project.activities`` (owned by pmis-project-management).
    Only the columns the SLA evaluation needs are declared."""

    __tablename__ = "activities"
    __table_args__ = {"schema": "project"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(36))
    milestone_id: Mapped[Optional[str]] = mapped_column(String(36))
    name: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[Optional[str]] = mapped_column(String(32))
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Soft-delete marker owned by project-management. Mirrored here so the
    # resolver can HIDE deleted activities — without it the contract would keep
    # resolving a soft-deleted activity as live and its SLA rows keep surfacing.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Project(MirrorBase):
    """Mirror of ``project.projects`` (owned by pmis-project-management).

    Only the planned ``start_date`` is needed here — it is the ANCHOR for the
    project-relative quarter math (see ``app.utilities.quarter``): quarters are
    measured from the project's start date rather than the absolute calendar,
    matching project-management's contract-relative period logic."""

    __tablename__ = "projects"
    __table_args__ = {"schema": "project"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
