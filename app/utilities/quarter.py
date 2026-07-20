"""Calendar-quarter helpers — IST-agnostic (uses the date's own Y/M).

Used by Phase B (SlaComplianceService.rollup_quarterly) and Phase D
(QuarterlySettlementService.close). Kept in this repo — not imported from
PMIS-project-management/app/utilities/cycle_calc.py — because
contract-management and project-management are separately deployable
services with no shared package.

RFP §5.27.6 (reporting interval = calendar quarter) treats Jan–Mar as Q1,
Apr–Jun as Q2, Jul–Sep as Q3, Oct–Dec as Q4. UIDAI's fiscal year begins
in April; we still store ``fiscal_year`` as the calendar year of the
quarter's first day to match the wire-level convention used by
project-management's cycle_calc._quarter_index — Phase D reconciles
against that FY convention if it ever diverges.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class QuarterKey:
    """Immutable, hashable calendar-quarter identifier + bounds.

    Two keys with the same (fiscal_year, quarter) are equal, so this can
    be a dict key or ``set`` member.
    """
    fiscal_year: int
    quarter: int          # 1..4
    quarter_start: date
    quarter_end: date

    def label(self) -> str:
        """Human string like ``2026-Q2`` — safe in filenames / URLs."""
        return f"{self.fiscal_year}-Q{self.quarter}"


def quarter_of(d: date) -> QuarterKey:
    """Calendar quarter (1..4) covering the given date."""
    q = (d.month - 1) // 3 + 1
    start_month = 3 * (q - 1) + 1
    start = date(d.year, start_month, 1)
    # Last day of quarter = day-before-start-of-next-quarter (handles Feb correctly).
    if q == 4:
        end = date(d.year, 12, 31)
    else:
        end = date(d.year, start_month + 3, 1).replace(day=1)
        end = date(end.year, end.month, 1)
        # subtract one day
        from datetime import timedelta
        end = end - timedelta(days=1)
    return QuarterKey(fiscal_year=d.year, quarter=q, quarter_start=start, quarter_end=end)


def previous_quarter(qk: QuarterKey) -> QuarterKey:
    """Quarter immediately preceding ``qk``. Wraps year at Q1→Q4."""
    if qk.quarter == 1:
        return quarter_of(date(qk.fiscal_year - 1, 10, 1))
    return quarter_of(date(qk.fiscal_year, 3 * (qk.quarter - 1), 1))


def parse_quarter_key(label: str) -> QuarterKey:
    """Reverse of ``QuarterKey.label()`` — takes '2026-Q2' → QuarterKey."""
    year_str, q_str = label.upper().split("-Q", 1)
    return quarter_of(date(int(year_str), 3 * (int(q_str) - 1) + 1, 1))
