"""Timezone helpers — single source for IST conversion + ISO formatting.

PMIS is a single-region deployment. All API responses emit datetimes in
IST (+05:30) so the FE doesn't have to translate. Stored values may be
naive UTC (legacy) or tz-aware; both flow through ``iso_ist`` cleanly.

Ported as-is from C:\\Programming\\PMIS\\PMIS-notification-service\\app\\utilities\\timezones.py:1-32.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


# IST = UTC+05:30. Hardcoded — no DST transitions to worry about.
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
    """Format a datetime as a tz-aware IST ISO-8601 string with the
    ``+05:30`` offset suffix.

    Behaviour:
      - ``None`` → ``None``
      - Naive datetime → assumed UTC, converted to IST.
      - tz-aware datetime → converted to IST.

    Matches monolith / user-mgmt ``iso_ist`` so all PMIS services emit
    response timestamps in the same shape.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat()
