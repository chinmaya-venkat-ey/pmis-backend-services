"""Cycle-count calculator — calendar-aligned buckets.

Buckets: month = calendar month; quarter = Q1 Jan-Mar / Q2 Apr-Jun / Q3 Jul-Sep
/ Q4 Oct-Dec; half = H1 Jan-Jun / H2 Jul-Dec; year = calendar year. Counting is
inclusive bucket-touch (cycles = endIndex − startIndex + 1).
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import ValidationError
from app.utilities import cycle_calc as cc


def _c(s, e, freq):
    return cc.count_cycles(date(*s), date(*e), freq)


# ---- the reported bug: half-yearly Dec 1 -> Mar 1 must be 2 ----------------

def test_half_yearly_dec_to_mar_is_two():
    # Dec 1 (H2 Jul-Dec) → Mar 1 (H1 Jan-Jun of next year) = 2 cycles
    assert _c((2025, 12, 1), (2026, 3, 1), cc.HALF_YEARLY) == 2


def test_half_yearly_within_one_half_is_one():
    assert _c((2026, 1, 1), (2026, 6, 30), cc.HALF_YEARLY) == 1   # Jan-Jun = H1
    assert _c((2026, 7, 1), (2026, 12, 31), cc.HALF_YEARLY) == 1  # Jul-Dec = H2


def test_half_yearly_full_calendar_year_is_two():
    assert _c((2026, 1, 1), (2026, 12, 31), cc.HALF_YEARLY) == 2


# ---- quarters (calendar) ---------------------------------------------------

def test_quarter_calendar_boundaries():
    assert _c((2026, 1, 1), (2026, 3, 31), cc.QUARTERLY) == 1     # Q1 Jan-Mar
    assert _c((2026, 3, 1), (2026, 4, 1), cc.QUARTERLY) == 2      # Q1 -> Q2 (Apr-Jun)
    assert _c((2026, 1, 1), (2026, 12, 31), cc.QUARTERLY) == 4    # full year = 4


# ---- months ----------------------------------------------------------------

def test_month_count():
    assert _c((2026, 1, 15), (2026, 1, 20), cc.MONTHLY) == 1
    assert _c((2025, 12, 1), (2026, 3, 1), cc.MONTHLY) == 4       # Dec,Jan,Feb,Mar


# ---- years (calendar) ------------------------------------------------------

def test_year_calendar():
    assert _c((2025, 12, 1), (2026, 3, 1), cc.YEARLY) == 2        # 2025 + 2026
    assert _c((2026, 1, 1), (2026, 12, 31), cc.YEARLY) == 1


# ---- guards ----------------------------------------------------------------

def test_inverted_range_raises():
    with pytest.raises(ValidationError):
        _c((2026, 3, 1), (2025, 12, 1), cc.MONTHLY)


def test_unsupported_frequency_raises():
    with pytest.raises(ValidationError):
        _c((2026, 1, 1), (2026, 2, 1), "weekly")


def test_overlong_span_raises():
    with pytest.raises(ValidationError):
        _c((2000, 1, 1), (2030, 1, 1), cc.YEARLY)
