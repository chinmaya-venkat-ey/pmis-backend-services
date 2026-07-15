"""Frequency-based carry-forward POOL — the dated installment schedule.

Per the payment contract (section 6, "the golden rule"): when a phase carries
its leftover forward by a FREQUENCY method (monthly / quarterly / half-yearly /
yearly), the money is NEVER added to any phase or milestone value. Instead it is
spread as a schedule of dated installments over the calendar periods AFTER the
carrying phase ends, up to the project end — a pool that invoicing later draws
from ("only at the time of invoicing is it decided how much carry to add").

Algorithm (matches the RFP's QGR worked example, and the spec given for this
build): with a leftover ``L``, a project spanning ``total`` periods at the
method's frequency and a carrying phase that ends after ``elapsed`` of them, the
``remaining = total - elapsed`` future periods each carry ``L / remaining``. The
rounding remainder lands on the LAST installment so the schedule sums to L
exactly. Periods are calendar-aligned buckets (same buckets as ``cycle_calc``);
a phase that ends mid-period is treated as having consumed that whole bucket
(inclusive bucket-touch), so installments begin at the next full period.

Pure date/decimal math — no DB, no side effects.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from app.utilities.cycle_calc import _INDEXERS, _to_ist_date

_ZERO = Decimal("0")
_Q = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(_Q, rounding=ROUND_HALF_UP)


def _as_date(d):
    """Normalise a datetime (tz-aware → IST) or date to a calendar ``date``."""
    if isinstance(d, datetime):
        return _to_ist_date(d)
    return d


def remaining_periods(project_end, phase_end, frequency):
    """How many whole ``frequency`` periods remain in the project AFTER a phase
    ends — the calendar buckets from just after ``phase_end`` up to ``project_end``.
    This is the number of installments the phase's leftover would spread over.
    Returns ``None`` when a date is missing or the frequency is unsupported; 0
    when the phase ends in (or after) the project's final bucket."""
    indexer = _INDEXERS.get(frequency)
    if indexer is None or not (project_end and phase_end):
        return None
    r = indexer(_as_date(project_end)) - indexer(_as_date(phase_end))
    return r if r > 0 else 0


# Frequency granularity, finest → coarsest. Periods nest exactly (1 quarter =
# 3 months, 1 half-year = 6 months, 1 year = 12 months), so when a phase mixes
# frequencies its recurring overlay is rendered on the FINEST cadence present
# and each coarser row lands as a lump on that timeline.
_GRANULARITY = {"monthly": 0, "quarterly": 1, "half_yearly": 2, "yearly": 3}


def finest_frequency(frequencies):
    """The most granular (finest) of ``frequencies``; None if none are
    recognised. Duplicates / unknown values are ignored."""
    known = [f for f in frequencies if f in _GRANULARITY]
    return min(known, key=_GRANULARITY.get) if known else None


def bucket_index(d, frequency):
    """The monotonic calendar-bucket index of date ``d`` at ``frequency`` (the
    same index space :func:`bucket_bounds` uses). None if the frequency is
    unsupported or ``d`` is missing."""
    indexer = _INDEXERS.get(frequency)
    if indexer is None or not d:
        return None
    return indexer(_as_date(d))


def _month_bounds(year: int, month: int):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def bucket_bounds(index: int, frequency: str):
    """Calendar start/end ``date`` of the ``frequency`` bucket at ``index`` (the
    same monotonic index ``cycle_calc`` uses)."""
    if frequency == "monthly":
        y, m = divmod(index, 12)
        return _month_bounds(y, m + 1)
    if frequency == "quarterly":
        y, q = divmod(index, 4)
        sm = q * 3 + 1
        return _month_bounds(y, sm)[0], _month_bounds(y, sm + 2)[1]
    if frequency == "half_yearly":
        y, h = divmod(index, 2)
        sm = h * 6 + 1
        return _month_bounds(y, sm)[0], _month_bounds(y, sm + 5)[1]
    if frequency == "yearly":
        return date(index, 1, 1), date(index, 12, 31)
    raise ValueError(f"unsupported frequency {frequency!r}")


def build_schedule(amount, start, end, frequency):
    """Distribute ``amount`` across the calendar ``frequency`` buckets spanning
    ``start`` → ``end`` INCLUSIVE — the schedule for a ``recurring_cost`` line
    (from the milestone-timeline start over the project duration).

    Unlike :func:`build_installments` (which spreads a phase's leftover over the
    buckets AFTER the phase ends), this includes the bucket containing ``start``.
    Returns ``[{"period_index", "period_start", "period_end", "amount"}]`` (period
    bounds are ``date``; amount is 2dp Decimal). Empty when ``amount`` ≤ 0, the
    frequency is unsupported, or a date is missing. Amounts sum to ``amount``
    exactly (the last installment absorbs the rounding remainder)."""
    indexer = _INDEXERS.get(frequency)
    total = Decimal(str(amount or 0))
    if indexer is None or total <= _ZERO or not (start and end):
        return []
    start_i = indexer(_as_date(start))
    end_i = indexer(_as_date(end))
    n = end_i - start_i + 1  # inclusive of both the start and end buckets
    if n <= 0:
        return []
    per = _round(total / Decimal(n))
    out = []
    allocated = _ZERO
    for k in range(n):
        i = start_i + k
        s, e = bucket_bounds(i, frequency)
        if k < n - 1:
            amt = per
            allocated = _round(allocated + amt)
        else:
            amt = _round(total - allocated)  # last installment absorbs the remainder
        out.append({"period_index": i, "period_start": s, "period_end": e, "amount": amt})
    return out


def build_installments(leftover, project_start, project_end, phase_end, frequency):
    """Return the dated installment schedule for ``leftover`` carried from a phase
    that ends at ``phase_end``, over the calendar periods up to ``project_end``.

    Returns a list of ``{"period_index", "period_start", "period_end", "amount"}``
    (period bounds are ``date``; amount is a 2dp Decimal). Empty when there is no
    future period (the phase ends in the project's final bucket), when the
    leftover is ≤ 0, or when the frequency is unsupported / dates are missing.
    The amounts sum to ``leftover`` exactly."""
    indexer = _INDEXERS.get(frequency)
    lo = Decimal(str(leftover or 0))
    if indexer is None or lo <= _ZERO or not (project_start and project_end and phase_end):
        return []
    proj_end_i = indexer(_as_date(project_end))
    phase_end_i = indexer(_as_date(phase_end))
    remaining = proj_end_i - phase_end_i
    if remaining <= 0:
        return []
    per = _round(lo / Decimal(remaining))
    out = []
    allocated = _ZERO
    for k in range(1, remaining + 1):
        i = phase_end_i + k
        s, e = bucket_bounds(i, frequency)
        if k < remaining:
            amt = per
            allocated = _round(allocated + amt)
        else:
            amt = _round(lo - allocated)  # last installment absorbs the rounding remainder
        out.append({"period_index": i, "period_start": s, "period_end": e, "amount": amt})
    return out
