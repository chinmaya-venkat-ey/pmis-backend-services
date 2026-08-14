"""Premise of the SLA008/009 first-quarter self-carry guard: previous_quarter
clamps the first anchored quarter to ITSELF, so the carry gate must skip when
prev_qk == qk (else the first breach quarter double-counts its own points)."""
from __future__ import annotations

from datetime import date

from app.utilities.quarter import previous_quarter, quarter_of


_ANCHOR = date(2026, 1, 1)  # project start → Y1-Q1 begins here


def test_previous_quarter_clamps_first_quarter_to_self():
    q1 = quarter_of(date(2026, 1, 15), _ANCHOR)   # Y1-Q1, anchored index 0
    assert q1.label() == "Y1-Q1"
    # The bug premise: previous_quarter of the first quarter is the quarter
    # itself (index clamped at 0) → the guard `prev_qk == qk` must catch this.
    assert previous_quarter(q1, _ANCHOR) == q1


def test_previous_quarter_steps_back_for_later_quarters():
    q2 = quarter_of(date(2026, 5, 15), _ANCHOR)   # Y1-Q2
    assert q2.label() == "Y1-Q2"
    prev = previous_quarter(q2, _ANCHOR)
    # Genuine carries (Q2 reading Q1, etc.) still pass the guard: prev != qk.
    assert prev != q2
    assert prev.label() == "Y1-Q1"


def test_calendar_fallback_never_self_carries():
    # Undated projects fall back to calendar quarters; previous_quarter there is
    # always a different quarter, so the self-carry bug never applied to them.
    cq = quarter_of(date(2026, 2, 1))             # calendar Q1 (no anchor)
    assert previous_quarter(cq) != cq
