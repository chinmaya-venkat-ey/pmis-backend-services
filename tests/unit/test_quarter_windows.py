"""quarter_windows tiles [start,end] into anchored 3-month buckets from the
start, last clamped to end; quarter_window_of returns the bucket containing a
date. Used to lay out / realign resource-based milestone activities."""
from __future__ import annotations

from datetime import date

from app.utilities.quarter_windows import quarter_window_of, quarter_windows


def test_tiles_milestone_into_quarters_last_clamped():
    # Jan 7 → Aug 8 spans 3 quarter buckets; last clamped to Aug 8.
    assert quarter_windows(date(2026, 1, 7), date(2026, 8, 8)) == [
        (date(2026, 1, 7), date(2026, 4, 6)),
        (date(2026, 4, 7), date(2026, 7, 6)),
        (date(2026, 7, 7), date(2026, 8, 8)),   # clamped to the milestone end
    ]


def test_exact_single_quarter():
    assert quarter_windows(date(2026, 1, 1), date(2026, 3, 31)) == [
        (date(2026, 1, 1), date(2026, 3, 31)),
    ]


def test_empty_when_end_before_start_or_missing():
    assert quarter_windows(date(2026, 4, 1), date(2026, 1, 1)) == []
    assert quarter_windows(None, date(2026, 1, 1)) == []
    assert quarter_windows(date(2026, 1, 1), None) == []


def test_window_of_snaps_to_containing_quarter():
    ms, me = date(2026, 1, 7), date(2026, 8, 8)
    assert quarter_window_of(date(2026, 1, 7), ms, me) == (date(2026, 1, 7), date(2026, 4, 6))
    assert quarter_window_of(date(2026, 4, 9), ms, me) == (date(2026, 4, 7), date(2026, 7, 6))
    assert quarter_window_of(date(2026, 5, 15), ms, me) == (date(2026, 4, 7), date(2026, 7, 6))
    # a date past the last window still clamps its end to the milestone end
    assert quarter_window_of(date(2026, 8, 1), ms, me) == (date(2026, 7, 7), date(2026, 8, 8))
