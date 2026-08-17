"""quarters_through enumerates the anchored quarter set from Y1-Q1 through the
quarter containing a date — the project's valid settlement-quarter span used by
the settlement refresh to regenerate quarters and prune orphans."""
from __future__ import annotations

from datetime import date

from app.utilities.quarter import quarters_through


def _labels(qks):
    return [qk.label() for qk in qks]


def test_spans_anchor_to_containing_quarter_inclusive():
    # Phase Jan 7 -> Aug 8 2026 spans Y1-Q1, Y1-Q2, Y1-Q3 (last contains Aug 8).
    qks = quarters_through(date(2026, 1, 7), date(2026, 8, 8))
    assert _labels(qks) == ["Y1-Q1", "Y1-Q2", "Y1-Q3"]
    assert (qks[0].quarter_start, qks[0].quarter_end) == (date(2026, 1, 7), date(2026, 4, 6))
    assert (qks[1].quarter_start, qks[1].quarter_end) == (date(2026, 4, 7), date(2026, 7, 6))
    assert (qks[2].quarter_start, qks[2].quarter_end) == (date(2026, 7, 7), date(2026, 10, 6))


def test_single_quarter_when_through_in_first_quarter():
    assert _labels(quarters_through(date(2026, 1, 7), date(2026, 2, 1))) == ["Y1-Q1"]


def test_through_on_anchor_is_just_q1():
    assert _labels(quarters_through(date(2026, 1, 7), date(2026, 1, 7))) == ["Y1-Q1"]


def test_through_before_anchor_clamps_to_q1():
    assert _labels(quarters_through(date(2026, 1, 7), date(2025, 6, 1))) == ["Y1-Q1"]


def test_crosses_into_second_contract_year():
    # Y2-Q1 is the 5th quarter [2027-01-07 .. 2027-04-06]; a date inside it
    # yields exactly 5 quarters.
    qks = quarters_through(date(2026, 1, 7), date(2027, 2, 1))
    assert _labels(qks) == ["Y1-Q1", "Y1-Q2", "Y1-Q3", "Y1-Q4", "Y2-Q1"]
    assert (qks[-1].quarter_start, qks[-1].quarter_end) == (date(2027, 1, 7), date(2027, 4, 6))
