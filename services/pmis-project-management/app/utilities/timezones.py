"""Timezone helpers — single source for IST conversion + ISO formatting.

Duplicated from services/pmis-user-management/app/utilities/timezones.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional


IST = timezone(timedelta(hours=5, minutes=30))


def iso_ist(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as tz-aware IST ISO-8601 with `+05:30` offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat()
