"""Cycle-count calculator — Project-Finance "number of cycles" utility.

Given a ``[start_date, end_date]`` window and a billing ``frequency``, returns
how many billing CYCLES the window spans, aligned to CALENDAR periods. Pure date
math — no DB, no project context.

Calendar buckets:
  - Month   : plain calendar month
  - Quarter : Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec
  - Half    : H1 Jan-Jun, H2 Jul-Dec
  - Year    : calendar year

Counting rule — inclusive "bucket-touch": a window that touches a bucket by even
one day counts it as one full cycle. So ``cycles = endIndex − startIndex + 1`` on
a monotonic per-frequency index; a calendar year is 4 quarters / 2 halves / 1
year / 12 months. Example: a half-yearly window Dec 1 → Mar 1 touches H2 (Jul-Dec)
then H1 (Jan-Jun) → 2 cycles.

Guards: ``end_date`` must be on/after ``start_date``; the window may not exceed
``MAX_SPAN_YEARS`` (10) — larger inputs raise ValidationError so a runaway range
(e.g. 500 years) can't blow up the count.
"""
from __future__ import annotations

from datetime import date, datetime

from app.core.errors import ValidationError
from app.utilities.timezones import IST


MAX_SPAN_YEARS = 10

# Supported frequency codes — a subset of the frequency master. weekly / daily /
# one_time are intentionally excluded for now (see the cycle-count contract).
MONTHLY = "monthly"
QUARTERLY = "quarterly"
HALF_YEARLY = "half_yearly"
YEARLY = "yearly"


def _month_index(d: date) -> int:
    """Monotonic calendar-month index."""
    return d.year * 12 + (d.month - 1)


def _quarter_index(d: date) -> int:
    """Monotonic CALENDAR-quarter index (Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec)."""
    return d.year * 4 + (d.month - 1) // 3


def _half_index(d: date) -> int:
    """Monotonic CALENDAR-half index (H1 Jan-Jun, H2 Jul-Dec)."""
    return d.year * 2 + (d.month - 1) // 6


def _year_index(d: date) -> int:
    """Monotonic calendar-year index."""
    return d.year


_INDEXERS = {
    MONTHLY: _month_index,
    QUARTERLY: _quarter_index,
    HALF_YEARLY: _half_index,
    YEARLY: _year_index,
}


def _add_years(d: date, n: int) -> date:
    """``d`` plus ``n`` years (Feb 29 → Feb 28 on a non-leap target year)."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def count_cycles(start_date: date, end_date: date, frequency: str) -> int:
    """Number of calendar-aligned ``frequency`` cycles the [start, end] window spans.

    Inclusive bucket-touch — a partial bucket still counts as one full cycle.
    Raises ValidationError on an inverted range, an over-long span (> 10 yrs),
    or an unsupported frequency.
    """
    if end_date < start_date:
        raise ValidationError(
            "endDate must be on or after startDate.",
            code="invalid_date_range",
            details={"startDate": start_date.isoformat(), "endDate": end_date.isoformat()},
        )
    if end_date > _add_years(start_date, MAX_SPAN_YEARS):
        raise ValidationError(
            f"The date range may not exceed {MAX_SPAN_YEARS} years.",
            code="date_span_too_large",
            details={"maxYears": MAX_SPAN_YEARS},
        )
    indexer = _INDEXERS.get(frequency)
    if indexer is None:
        raise ValidationError(
            f"Unsupported frequency {frequency!r}.",
            code="unsupported_frequency",
            details={"supported": sorted(_INDEXERS)},
        )
    return indexer(end_date) - indexer(start_date) + 1


def _to_ist_date(dt: datetime) -> date:
    """Calendar date of ``dt`` in IST (tz-aware → IST before the date is taken,
    so a UTC instant already 'tomorrow' in IST buckets correctly; naive values
    pass through). Matches the project's IST-everywhere convention."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST)
    return dt.date()


def count_cycles_from_datetimes(start: datetime, end: datetime, frequency: str) -> int:
    """``count_cycles`` for ``datetime`` inputs — the on-the-wire type used by
    milestones/projects. Normalizes each to the IST calendar date first."""
    return count_cycles(_to_ist_date(start), _to_ist_date(end), frequency)
