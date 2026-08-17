"""Resolve a project's quarter ANCHOR — the resource-phase start.

Quarters in this service are measured FROM the anchor (see
``app.utilities.quarter``). The anchor is the **resource-based phase start** —
the earliest resource-based milestone's ``start_date`` — because a project's
inception can be months or years before any resources deploy, and anchoring on
the project start would scatter the resource activities across quarters that
don't line up with the phase (leaving some quarters empty and mis-bucketing
others across a boundary). When a project has NO resource-based milestone we
fall back to its own planned ``start_date`` (the legacy project-start anchor);
``None`` when the project is unknown / undated — callers then fall back to
legacy calendar quarters.

NOTE: this is the SLA/settlement QUARTER anchor only. The rate-card contract
YEAR stays anchored on the project start in project-management
(``resource_rate.contract_year_no``) — rates are contract-year-based and F reads
the already-snapshotted ``computed_cost``, so the two anchors are independent.

Reads cross-schema from ``project.milestones`` / ``project.projects`` (same
read-only pattern as the SLA activity lookups) and normalises to an IST date.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text
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
    """The SLA/settlement quarter anchor as an IST date: the earliest
    resource-based milestone start (the resource-phase start), falling back to
    the project's own ``start_date`` when there is no resource-based milestone,
    and ``None`` when the project is unknown / undated. See the module docstring.
    """
    if not project_id:
        return None
    # Resource-phase start = earliest resource-based milestone's start.
    rb_start = db.execute(
        text(
            """
            SELECT MIN(start_date)
              FROM project.milestones
             WHERE project_id = :pid
               AND is_resource_based = TRUE
            """
        ),
        {"pid": project_id},
    ).scalar()
    if rb_start is not None:
        return _to_ist_date(rb_start)
    # Fallback: the project's own planned start (legacy project-start anchor).
    row = db.execute(
        select(Project.start_date).where(Project.id == project_id)
    ).first()
    return _to_ist_date(row[0]) if row else None


def project_phase_end(db: Session, project_id: Optional[str]) -> Optional[date]:
    """The resource-phase END as an IST date: the LATEST resource-based
    milestone end, falling back to the project's own ``end_date`` when there is
    no resource-based milestone, and ``None`` when unknown / undated.

    Paired with :func:`project_anchor` (the phase START) it bounds the project's
    valid settlement-quarter span — the settlement refresh enumerates quarters
    across ``[anchor, phase_end]`` (clamped to today) and prunes any stored
    period outside it."""
    if not project_id:
        return None
    rb_end = db.execute(
        text(
            """
            SELECT MAX(end_date)
              FROM project.milestones
             WHERE project_id = :pid
               AND is_resource_based = TRUE
            """
        ),
        {"pid": project_id},
    ).scalar()
    if rb_end is not None:
        return _to_ist_date(rb_end)
    row = db.execute(
        select(Project.end_date).where(Project.id == project_id)
    ).first()
    return _to_ist_date(row[0]) if row else None
