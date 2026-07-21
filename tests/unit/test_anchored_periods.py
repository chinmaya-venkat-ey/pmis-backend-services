"""Contract-relative (anchored) period math — bugs #325 / #327.

When an ``anchor`` (the project/contract start date) is supplied, buckets are
measured FROM that date instead of the absolute calendar. ``anchor=None``
preserves the legacy calendar behaviour (covered by test_cf_pool /
test_cycle_calc), so these tests focus on the anchored path + parity.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.utilities import cf_pool, cycle_calc

# Contract running Apr 1 2026 → Mar 31 2029 (fiscal-year aligned, NOT calendar).
ANCHOR = date(2026, 4, 1)
C_START = date(2026, 4, 1)
C_END = date(2029, 3, 31)


# ---- #327 recurring schedule ------------------------------------------------

def test_recurring_yearly_follows_contract_year():
    inst = cf_pool.build_schedule(900000, C_START, C_END, "yearly", anchor=ANCHOR)
    assert len(inst) == 3
    assert all(x["amount"] == Decimal("300000.00") for x in inst)
    assert sum(x["amount"] for x in inst) == Decimal("900000.00")
    # buckets are Apr 1 → Mar 31 contract years, not Jan–Dec calendar years
    assert (inst[0]["period_start"], inst[0]["period_end"]) == (date(2026, 4, 1), date(2027, 3, 31))
    assert (inst[2]["period_start"], inst[2]["period_end"]) == (date(2028, 4, 1), date(2029, 3, 31))


def test_recurring_legacy_calendar_unchanged():
    inst = cf_pool.build_schedule(900000, C_START, C_END, "yearly")  # no anchor
    assert len(inst) == 4  # touches calendar years 2026/27/28/29
    assert inst[0]["period_end"] == date(2026, 12, 31)


def test_recurring_quarterly_anchored():
    # one contract year, quarterly → exactly 4 quarters from Apr 1
    inst = cf_pool.build_schedule(400000, date(2026, 4, 1), date(2027, 3, 31),
                                  "quarterly", anchor=ANCHOR)
    assert len(inst) == 4
    assert inst[0]["period_start"] == date(2026, 4, 1)
    assert inst[0]["period_end"] == date(2026, 6, 30)
    assert inst[3]["period_end"] == date(2027, 3, 31)


# ---- #325 cycle counts ------------------------------------------------------

def test_cycle_count_contract_vs_calendar():
    assert cycle_calc.count_cycles(C_START, C_END, "yearly", anchor=ANCHOR) == 3
    assert cycle_calc.count_cycles(C_START, C_END, "yearly") == 4  # legacy calendar


def test_cycle_count_single_contract_year():
    assert cycle_calc.count_cycles(date(2026, 4, 1), date(2027, 3, 31), "yearly", anchor=ANCHOR) == 1


# ---- #325 carry-forward pool remaining periods ------------------------------

def test_remaining_periods_anchored():
    # phase ends Sep 30 2027 → only contract-year 3 (Apr28–Mar29) remains
    assert cf_pool.remaining_periods(C_END, date(2027, 9, 30), "yearly", anchor=ANCHOR) == 1
    assert cf_pool.remaining_periods(C_END, date(2027, 9, 30), "yearly") == 2  # legacy


def test_installments_anchored_sum_conserved():
    inst = cf_pool.build_installments(100000, C_START, C_END, date(2027, 9, 30),
                                      "yearly", anchor=ANCHOR)
    assert len(inst) == 1
    assert inst[0]["amount"] == Decimal("100000.00")
    assert inst[0]["period_start"] == date(2028, 4, 1)
    assert inst[0]["period_end"] == date(2029, 3, 31)


# ---- anchored bucket bounds -------------------------------------------------

def test_bucket_bounds_anchored():
    assert cf_pool.bucket_bounds(0, "yearly", anchor=ANCHOR) == (date(2026, 4, 1), date(2027, 3, 31))
    assert cf_pool.bucket_bounds(1, "quarterly", anchor=ANCHOR) == (date(2026, 7, 1), date(2026, 9, 30))
