"""Timezone helpers — single source for IST conversion + ISO formatting.

Duplicated from services/pmis-masters-management/app/utilities/timezones.py
(promoted to canonical here in user-svc).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Canonical "current time" for PMIS — tz-aware IST datetime.

    Use everywhere instead of ``datetime.utcnow`` / ``datetime.now(timezone.utc)``
    so timestamps are consistently IST throughout the stack. Safe to use as a
    SQLAlchemy column default (``default=now_ist``) — pass the callable, not
    its result.
    """
    return datetime.now(IST)


def iso_ist(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as tz-aware IST ISO-8601 with `+05:30` offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat()
