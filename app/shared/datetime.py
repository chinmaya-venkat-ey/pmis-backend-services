"""
DateTime utilities.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional


# IST is UTC+05:30. PMIS is single-region (India / UIDAI) so we hardcode
# rather than read from a tz database — no DST transitions to worry about.
IST = timezone(timedelta(hours=5, minutes=30))


def to_ist_calendar_midnight(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize ``dt`` to IST midnight of its IST-local calendar date.

    Doc 29 (date-equality cross-format fix): the PMIS UI is calendar-
    date-driven. A user picks "May 4" on a date widget; what they mean
    is "the calendar date May 4 in IST", not "May 4 at some arbitrary
    instant". Different FE form components serialize the same picked
    date inconsistently:

      - "2026-05-04T00:00:00+05:30"   IST midnight (most pickers)
      - "2026-05-04T00:00:00.000Z"    UTC midnight  (some pickers)
      - "2026-05-04T23:59:59+05:30"   IST end-of-day (other pickers)
      - "2026-05-04T23:59:59.000Z"    UTC end-of-day
      - "2026-05-04T23:59:59"         naive (treated as UTC)

    All of these represent "May 4" to the user but produce different
    UTC instants. When the BE compares them across entities (project
    vs milestone), inputs that the user picked as the same calendar
    date land 5h30m–24h apart and trip lower-bound rejections.

    This helper collapses any submitted datetime to a single canonical
    instant: ``YYYY-MM-DDT00:00:00+05:30`` (IST midnight of the IST-
    local calendar date). Combined with ``UtcDateTime`` storage, all
    "May 4" inputs end up as the same stored value
    (``2026-05-03 18:30:00`` UTC), and comparisons become trivially
    correct.

    Behavior:
      * ``None``        → ``None``
      * tz-aware input  → converted to IST → date extracted → midnight IST
      * naive input     → assumed UTC → converted to IST → date extracted → midnight IST

    Returns a tz-aware datetime so ``UtcDateTime``'s bind path converts
    it correctly on storage.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive as UTC (matches ``ensure_aware_utc`` semantics).
        dt = dt.replace(tzinfo=timezone.utc)
    ist_dt = dt.astimezone(IST)
    return datetime(ist_dt.year, ist_dt.month, ist_dt.day, tzinfo=IST)


def _validate_ist_calendar_midnight(value):
    """Pydantic-friendly wrapper for ``to_ist_calendar_midnight``.

    Pydantic 2's AfterValidator passes the parsed ``datetime``; we
    normalize and return. None passes through. Non-datetime inputs (an
    upstream parser problem, not ours) pass through to let Pydantic
    raise its own type error.
    """
    if value is None or not isinstance(value, datetime):
        return value
    return to_ist_calendar_midnight(value)


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


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as a tz-aware UTC ISO 8601 string.

    Doc 27 part 2 (response-format consistency): every API response
    should emit datetimes with an explicit ``+00:00`` (UTC) suffix, so
    FE date pickers / locale converters can reliably interpret them
    without having to guess whether a naive value means UTC or local.

    Behavior:
      - ``None`` → ``None``
      - Naive datetime → assumed UTC; suffix attached.
      - tz-aware datetime → converted to UTC; suffix attached.

    Pairs with ``app/infrastructure/db/utc_datetime.UtcDateTime``: that
    type guarantees stored values are canonical naive UTC; this helper
    guarantees responses re-attach the ``+00:00`` so FE never sees a
    bare naive datetime.

    Doc 53: kept for back-compat but most callers should use
    ``iso_ist`` instead so user-mgmt response timestamps align with
    monolith/project-mgmt (IST with ``+05:30`` offset). Update one
    call site at a time as needed.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def iso_ist(dt: Optional[datetime]) -> Optional[str]:
    """Format a datetime as a tz-aware IST ISO 8601 string
    (``+05:30`` offset).

    Doc 53: user-mgmt response timestamps now emit IST to match
    monolith / project-mgmt. The stored value is still naive UTC
    (via ``UtcDateTime``); this helper converts to IST on the way
    out.

    Behavior:
      - ``None`` → ``None``
      - Naive datetime → assumed UTC, converted to IST, ``+05:30`` suffix.
      - tz-aware datetime → converted to IST, ``+05:30`` suffix.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat()


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


# ---------------------------------------------------------------------------
# Pydantic-friendly annotated type — schemas use this in place of ``datetime``
# for any field whose semantics is calendar-date (M-A-T-S start/end). After
# Pydantic parses the incoming string into a datetime, the AfterValidator
# normalizes it to IST midnight of the IST-local calendar date.
# ---------------------------------------------------------------------------
try:
    from pydantic import AfterValidator  # type: ignore
    IstCalendarDate = Annotated[datetime, AfterValidator(_validate_ist_calendar_midnight)]
except ImportError:
    # Pydantic isn't required at import time for shared utilities; the type
    # is only used inside schema modules which already depend on it.
    IstCalendarDate = datetime  # fallback (no normalization)
