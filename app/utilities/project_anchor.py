"""Resolve a project's quarter ANCHOR — its planned start date.

Quarters in this service are measured FROM the project start date (see
``app.utilities.quarter``), mirroring project-management's contract-relative
period math. This helper reads the planned ``start_date`` from the shared
``project.projects`` table (cross-schema, same read-only pattern as the SLA
cron's activity lookups) and normalises it to an IST calendar date.

Returns ``None`` when the project is unknown or has no start date — callers
then fall back to legacy calendar quarters so undated projects still resolve
to a stable bucket.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import Project

# IST is a fixed +05:30 offset (no DST) — matches project-management's
# IST-everywhere convention for turning a stored instant into a calendar date.
_IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(_IST)
        return value.date()
    return value  # already a date


def project_anchor(db: Session, project_id: Optional[str]) -> Optional[date]:
    """Planned project start date (the quarter anchor) as an IST date, or
    ``None`` when the project is unknown / has no start date."""
    if not project_id:
        return None
    row = db.execute(
        select(Project.start_date).where(Project.id == project_id)
    ).first()
    return _to_ist_date(row[0]) if row else None
