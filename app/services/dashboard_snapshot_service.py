"""Dashboard snapshot service — persists daily KPI values and derives the
``delta`` / ``spark`` fields the summary dashboard shows.

Write side: the shared-secret cron endpoint hands us a ``{metric_key:
value}`` dict for a date; ``write_snapshot`` upserts one row per metric
(idempotent per (date, scope, metric)).

Read side: ``delta_spark(metric_key, current_value)`` returns
``(delta_string_or_None, spark_list)``:
  * ``spark`` — the metric's value at the end of each of the last 6
    calendar months (latest snapshot on/before each month-end), with the
    current value as the final point, in DISPLAY units (crore for money).
    Returns ``[]`` when there isn't enough history (< 2 points).
  * ``delta`` — ``current - value_at_end_of_previous_month`` formatted per
    metric kind ("+6 vs last month" / "+3% vs last month" /
    "+120 Cr vs last month"). ``None`` when no prior-month snapshot exists.

No history yet => delta None, spark [] — the dashboard degrades cleanly
(exactly the Phase-A behaviour) until the cron has run for a while.
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dashboard_metric_snapshot import DashboardMetricSnapshot

_CRORE = Decimal("10000000")

# Metric kind drives display units + delta formatting.
#   count   -> integer, "+N vs last month"
#   percent -> integer, "+N% vs last month"
#   money   -> crore,   "+N Cr vs last month"
METRIC_KINDS: Dict[str, str] = {
    "total_projects": "count",
    "ontrack_pct": "percent",
    "delayed_projects": "count",
    "contract_value": "money",
    "released": "money",
    "sla_compliance": "percent",
}

# The metric set captured for the global scope each run.
GLOBAL_METRIC_KEYS: Tuple[str, ...] = tuple(METRIC_KINDS.keys())


def _display(value: Decimal, kind: str):
    """Raw value -> display number (crore for money, int otherwise)."""
    if kind == "money":
        cr = float(value / _CRORE)
        return int(cr) if float(cr).is_integer() else round(cr, 2)
    f = float(value)
    return int(round(f))


def _fmt_delta(diff_display, kind: str) -> str:
    sign = "+" if diff_display >= 0 else "-"
    mag = abs(diff_display)
    if kind == "percent":
        return f"{sign}{mag}% vs last month"
    if kind == "money":
        return f"{sign}{mag} Cr vs last month"
    return f"{sign}{mag} vs last month"


def _month_end(year: int, month: int) -> _date:
    """Last calendar day of (year, month)."""
    if month == 12:
        return _date(year, 12, 31)
    return _date(year, month + 1, 1) - _timedelta(days=1)


class DashboardSnapshotService:
    def __init__(self, db: Session):
        self.db = db

    # ---- write ----------------------------------------------------------

    def write_snapshot(
        self,
        *,
        captured_date: _date,
        metrics: Dict[str, Decimal],
        scope_type: str = "global",
        scope_id: str = "",
    ) -> int:
        """Upsert one row per metric for ``captured_date``. Returns the
        number of metrics written. Commits."""
        existing = {
            row.metric_key: row
            for row in self.db.execute(
                select(DashboardMetricSnapshot)
                .where(DashboardMetricSnapshot.captured_date == captured_date)
                .where(DashboardMetricSnapshot.scope_type == scope_type)
                .where(DashboardMetricSnapshot.scope_id == scope_id)
            ).scalars().all()
        }
        for key, value in metrics.items():
            val = Decimal(value or 0)
            row = existing.get(key)
            if row is not None:
                row.value = val
            else:
                self.db.add(DashboardMetricSnapshot(
                    id=str(uuid4()),
                    captured_date=captured_date,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    metric_key=key,
                    value=val,
                ))
        self.db.commit()
        return len(metrics)

    # ---- read -----------------------------------------------------------

    def _value_on_or_before(
        self, metric_key: str, cutoff: _date, scope_type: str, scope_id: str,
    ) -> Optional[Decimal]:
        row = self.db.execute(
            select(DashboardMetricSnapshot.value)
            .where(DashboardMetricSnapshot.metric_key == metric_key)
            .where(DashboardMetricSnapshot.scope_type == scope_type)
            .where(DashboardMetricSnapshot.scope_id == scope_id)
            .where(DashboardMetricSnapshot.captured_date <= cutoff)
            .order_by(DashboardMetricSnapshot.captured_date.desc())
            .limit(1)
        ).first()
        return row[0] if row else None

    def delta_spark(
        self,
        metric_key: str,
        current_value: Decimal,
        *,
        today: _date,
        scope_type: str = "global",
        scope_id: str = "",
    ) -> Tuple[Optional[str], List]:
        kind = METRIC_KINDS.get(metric_key, "count")
        current = Decimal(current_value or 0)

        # --- spark: last 6 month-ends + current ---
        months: List[Tuple[int, int]] = []
        y, m = today.year, today.month
        for _ in range(6):
            months.append((y, m))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        months.reverse()  # oldest -> newest

        spark: List = []
        for (yy, mm) in months[:-1]:
            v = self._value_on_or_before(metric_key, _month_end(yy, mm), scope_type, scope_id)
            if v is not None:
                spark.append(_display(v, kind))
        spark.append(_display(current, kind))  # newest point = live value
        if len(spark) < 2:
            spark = []

        # --- delta: current vs end of previous calendar month ---
        py, pm = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        prev = self._value_on_or_before(metric_key, _month_end(py, pm), scope_type, scope_id)
        delta: Optional[str] = None
        if prev is not None:
            diff = _display(current, kind) - _display(prev, kind)
            delta = _fmt_delta(diff, kind)

        return delta, spark
