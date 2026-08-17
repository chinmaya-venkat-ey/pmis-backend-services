"""Project-anchored quarter helpers.

Quarters are measured FROM the project's start date (the ANCHOR), mirroring
project-management's contract-relative period math (``cf_pool`` / ``cycle_calc``,
bug #325/#327). Quarter bucket ``k`` spans::

    [ anchor + 3k months ,  anchor + 3(k+1) months − 1 day ]

Bucket 0 begins on the project start; the anchor's day-of-month defines every
boundary. Quarters are then labelled CONTRACT-RELATIVE — ``Y1-Q1`` is the first
quarter from the project start, ``Y1-Q4`` the fourth, ``Y2-Q1`` the fifth …::

    fiscal_year = contract year (1-based)  = k // 4 + 1
    quarter     = quarter within that year = k %  4 + 1

When no anchor is available (project start date missing) we fall back to the
legacy CALENDAR quarter — Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec,
``fiscal_year`` = the calendar year — so undated projects still resolve to a
stable bucket. Anchored keys label as ``Y{yr}-Q{q}``; calendar-fallback keys
keep the legacy ``{yyyy}-Q{q}`` form.

Self-contained — NOT imported from ``PMIS-project-management/app/utilities``
because contract-management and project-management are separately deployable
services with no shared package. The anchored math here is a faithful copy of
``cf_pool``'s contract-relative bucket logic for the quarterly cadence.

Callers resolve the anchor via ``app.utilities.project_anchor.project_anchor``
(the project's planned start date) and pass it in.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

_QUARTER_MONTHS = 3


# ── anchored (contract-relative) date math — copy of cf_pool's quarterly logic ──

def _add_months(d: date, n: int) -> date:
    """``d`` plus ``n`` calendar months, clamping the day to the target month's
    length (Jan 31 + 1 month → Feb 28/29). ``n`` may be negative."""
    m0 = d.year * 12 + (d.month - 1) + n
    year, month = divmod(m0, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def _anchored_quarter_index(d: date, anchor: date) -> int:
    """Contract-relative quarter bucket index of ``d`` measured from ``anchor``.

    Clamped at 0 — a date on/before the project start falls in bucket 0
    (``Y1-Q1``), matching project-management's ``contract_year_no`` clamp so an
    out-of-contract date never yields a negative / ``Y0`` quarter."""
    months = (d.year - anchor.year) * 12 + (d.month - anchor.month)
    if d.day < anchor.day:              # the anchor day-of-month is the boundary
        months -= 1
    idx = months // _QUARTER_MONTHS     # floor-div → monotonic across the anchor
    return idx if idx > 0 else 0


def _anchored_bounds(index: int, anchor: date):
    """Start/end ``date`` of anchored quarter ``index`` — bucket ``k`` spans
    ``[anchor + 3k months, next boundary − 1 day]``."""
    start = _add_months(anchor, index * _QUARTER_MONTHS)
    end = _add_months(anchor, (index + 1) * _QUARTER_MONTHS) - timedelta(days=1)
    return start, end


@dataclass(frozen=True)
class QuarterKey:
    """Immutable, hashable quarter identifier + bounds.

    Anchored keys carry the CONTRACT year in ``fiscal_year`` (1-based) and the
    quarter-within-that-year (1..4) in ``quarter``; calendar-fallback keys carry
    the calendar year and the calendar quarter. Two keys with the same
    (fiscal_year, quarter, anchored) describe the same period for a given
    project, so this stays usable as a dict key / ``set`` member.
    """
    fiscal_year: int
    quarter: int          # 1..4
    quarter_start: date
    quarter_end: date
    anchored: bool = True

    def label(self) -> str:
        """Human string. Anchored: ``Y1-Q2``. Calendar fallback: ``2026-Q2``.
        Safe in filenames / URLs / invoice refs."""
        if self.anchored:
            return f"Y{self.fiscal_year}-Q{self.quarter}"
        return f"{self.fiscal_year}-Q{self.quarter}"


# ── calendar fallback (legacy, anchor unknown) ────────────────────────────────

def _calendar_quarter_of(d: date) -> QuarterKey:
    """Legacy calendar quarter (Q1 Jan-Mar … Q4 Oct-Dec)."""
    q = (d.month - 1) // 3 + 1
    start_month = 3 * (q - 1) + 1
    start = date(d.year, start_month, 1)
    if q == 4:
        end = date(d.year, 12, 31)
    else:
        end = date(d.year, start_month + 3, 1) - timedelta(days=1)
    return QuarterKey(fiscal_year=d.year, quarter=q,
                      quarter_start=start, quarter_end=end, anchored=False)


# ── public API — anchored when ``anchor`` given, else calendar fallback ───────

def _key_from_index(index: int, anchor: date) -> QuarterKey:
    start, end = _anchored_bounds(index, anchor)
    return QuarterKey(
        fiscal_year=index // 4 + 1,
        quarter=index % 4 + 1,
        quarter_start=start,
        quarter_end=end,
        anchored=True,
    )


def quarter_of(d: date, anchor: Optional[date] = None) -> QuarterKey:
    """Quarter covering ``d``. Contract-relative when ``anchor`` (the project
    start date) is given; legacy calendar quarter otherwise."""
    if anchor is None:
        return _calendar_quarter_of(d)
    return _key_from_index(_anchored_quarter_index(d, anchor), anchor)


def quarters_through(anchor: date, through: date) -> list[QuarterKey]:
    """Every anchored quarter from ``Y1-Q1`` through the quarter that CONTAINS
    ``through`` (inclusive) — the project's valid settlement-quarter set.

    ``through`` before the anchor collapses to just ``Y1-Q1`` (the index is
    clamped at 0). Anchored-only: callers with no anchor (undated projects) use
    the legacy calendar path and never enumerate. Used by the settlement refresh
    to regenerate the correct quarters and prune orphans left by an anchor
    change."""
    last = _anchored_quarter_index(through, anchor) if through >= anchor else 0
    return [_key_from_index(k, anchor) for k in range(last + 1)]


def previous_quarter(qk: QuarterKey, anchor: Optional[date] = None) -> QuarterKey:
    """Quarter immediately preceding ``qk``.

    Anchored: index − 1, clamped at 0 (there is no quarter before the project
    start). Calendar fallback: wraps the year at Q1→Q4."""
    if anchor is not None and qk.anchored:
        idx = (qk.fiscal_year - 1) * 4 + (qk.quarter - 1)
        return _key_from_index(max(0, idx - 1), anchor)
    # calendar fallback
    if qk.quarter == 1:
        return _calendar_quarter_of(date(qk.fiscal_year - 1, 10, 1))
    return _calendar_quarter_of(date(qk.fiscal_year, 3 * (qk.quarter - 1), 1))


def parse_quarter_key(label: str, anchor: Optional[date] = None) -> QuarterKey:
    """Reverse of :meth:`QuarterKey.label`.

    ``Y1-Q2`` → contract-relative (requires ``anchor``); ``2026-Q2`` → legacy
    calendar. Raises ``ValueError`` on a malformed label or a contract-relative
    label with no anchor."""
    up = label.upper().strip()
    year_str, q_str = up.split("-Q", 1)
    quarter = int(q_str)
    if not 1 <= quarter <= 4:
        raise ValueError(f"quarter must be 1..4, got {quarter}")
    if year_str.startswith("Y"):
        year_no = int(year_str[1:])
        if year_no < 1:
            raise ValueError(f"contract year must be >= 1, got {year_no}")
        if anchor is None:
            raise ValueError(
                f"contract-relative quarter {label!r} needs a project anchor")
        return _key_from_index((year_no - 1) * 4 + (quarter - 1), anchor)
    # legacy calendar label
    return _calendar_quarter_of(date(int(year_str), 3 * (quarter - 1) + 1, 1))
