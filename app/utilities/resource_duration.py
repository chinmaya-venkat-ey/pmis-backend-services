"""Convert a resource's deployment window into a fractional DURATION IN MONTHS.

Planned-resource cost = ``quantity × monthly_rate × duration_months``. This
module owns the deployment-window → months conversion:
``months = (inclusive day span) / 30.4375`` (average calendar days per month),
2 dp, floored at 0.

A monthly rate is billed per man-month, so there is no working-hours / leaveConfig
model here (that was the earlier hourly design).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

# Average calendar days per month (365.25 / 12).
_DAYS_PER_MONTH = Decimal("30.4375")


def _as_date(v):
    """Accept a date or datetime; return a date (or None)."""
    if v is None:
        return None
    return v.date() if hasattr(v, "date") and not isinstance(v, date) else v


def duration_months(deploy_start, deploy_end) -> Decimal:
    """Fractional months spanned by ``[deploy_start, deploy_end]`` inclusive:
    ``(days + 1) / 30.4375``, 2 dp, floored at 0. Missing dates or end < start
    → 0 (e.g. Apr 1 – Jun 30 = 91 days → 2.99 months)."""
    start = _as_date(deploy_start)
    end = _as_date(deploy_end)
    if start is None or end is None or end < start:
        return Decimal("0")
    days = Decimal((end - start).days + 1)
    return (days / _DAYS_PER_MONTH).quantize(Decimal("0.01"))
