"""
DateTime utilities.
"""
from datetime import datetime, timezone
from typing import Optional


def ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return a timezone-aware UTC datetime.

    If ``dt`` is naive, assume UTC and attach tzinfo. If aware, convert to UTC.
    Use this before comparing user-supplied datetimes (which may be naive or
    aware depending on client) against DB values or ``datetime.now(utc)``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """
    Format datetime to ISO 8601 string.

    Args:
        dt: Datetime to format

    Returns:
        ISO 8601 formatted string or None
    """
    if dt is None:
        return None

    return dt.isoformat()


def parse_datetime(dt_str: str) -> Optional[datetime]:
    """
    Parse ISO 8601 datetime string.

    Args:
        dt_str: ISO 8601 datetime string

    Returns:
        Datetime object or None if parsing fails
    """
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, AttributeError):
        return None
