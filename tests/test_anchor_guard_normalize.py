"""Anchor write-guard core: a calendar (un-anchored) quarter key for a project
that HAS a start-date anchor must normalise to the contract-relative fiscal_year
before the aggregate is persisted — so a mixed deployment (a stale pre-anchoring
build sharing the DB) can't create calendar-year duplicate rows.

The guard in SlaComplianceService.rollup_mapping_for_quarter re-derives
``quarter_of(qk.quarter_start, anchor)`` when ``not qk.anchored``; this pins that
re-derivation invariant (the DB-integration path is exercised by the service)."""
from __future__ import annotations

from datetime import date

from app.utilities.quarter import quarter_of

# d1a547ef starts 2026-01-01-ish; use a clean 1st-of-month anchor.
_ANCHOR = date(2025, 1, 1)


def test_calendar_qk_reanchors_to_contract_year():
    cal = quarter_of(date(2026, 7, 1), None)          # calendar fallback
    assert cal.anchored is False
    assert cal.fiscal_year == 2026 and cal.quarter == 3

    # What the guard does: re-derive off quarter_start with the project anchor.
    fixed = quarter_of(cal.quarter_start, _ANCHOR)
    assert fixed.anchored is True
    assert fixed.fiscal_year == 2 and fixed.quarter == 3   # Y2-Q3
    # Same real quarter window — only the (fiscal_year, quarter) label changes.
    assert fixed.quarter_start == cal.quarter_start
    assert fixed.quarter_end == cal.quarter_end


def test_already_anchored_qk_is_untouched_by_rederivation():
    anchored = quarter_of(date(2026, 7, 1), _ANCHOR)
    assert anchored.anchored is True
    # Guard only fires for `not qk.anchored`; re-deriving an anchored key is a
    # no-op that yields the same key.
    assert quarter_of(anchored.quarter_start, _ANCHOR) == anchored


def test_undated_project_keeps_calendar_quarter():
    # Genuinely-undated project (anchor None) legitimately stays on calendar
    # quarters — the guard's `anchor is not None` check leaves these alone.
    cal = quarter_of(date(2026, 4, 10), None)
    assert cal.anchored is False and cal.fiscal_year == 2026
