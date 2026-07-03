"""Frequency-based carry-forward pool — the dated installment generator."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.utilities import cf_pool


def test_qgr_example_quarterly():
    # RFP's QGR: 350 over 26 quarters, phase ends quarter 6 → 20 × 17.50.
    inst = cf_pool.build_installments(
        Decimal("350"), date(2027, 1, 1), date(2033, 6, 30), date(2028, 6, 30), "quarterly")
    assert len(inst) == 20
    assert all(x["amount"] == Decimal("17.50") for x in inst)
    assert sum(x["amount"] for x in inst) == Decimal("350.00")
    assert inst[0]["period_start"] == date(2028, 7, 1)     # next quarter after phase end
    assert inst[-1]["period_end"] == date(2033, 6, 30)     # project end bucket


def test_rounding_remainder_on_last_installment():
    # 100 over 3 periods → 33.33, 33.33, 33.34 (sums to 100 exactly).
    inst = cf_pool.build_installments(
        Decimal("100"), date(2030, 1, 1), date(2030, 12, 31), date(2030, 9, 30), "monthly")
    assert [x["amount"] for x in inst] == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(x["amount"] for x in inst) == Decimal("100.00")


def test_bucket_bounds_calendar_aligned():
    assert cf_pool.bucket_bounds(cf_pool._INDEXERS["quarterly"](date(2028, 8, 15)), "quarterly") \
        == (date(2028, 7, 1), date(2028, 9, 30))
    assert cf_pool.bucket_bounds(cf_pool._INDEXERS["half_yearly"](date(2028, 3, 1)), "half_yearly") \
        == (date(2028, 1, 1), date(2028, 6, 30))
    assert cf_pool.bucket_bounds(cf_pool._INDEXERS["yearly"](date(2028, 5, 1)), "yearly") \
        == (date(2028, 1, 1), date(2028, 12, 31))


def test_no_future_period_returns_empty():
    # Phase ends in the project's final bucket → nothing to schedule.
    assert cf_pool.build_installments(
        Decimal("500"), date(2030, 1, 1), date(2030, 12, 31), date(2030, 12, 31), "quarterly") == []


def test_zero_or_missing_inputs():
    assert cf_pool.build_installments(Decimal("0"), date(2030, 1, 1), date(2031, 1, 1),
                                      date(2030, 6, 1), "quarterly") == []
    assert cf_pool.build_installments(Decimal("100"), None, None, None, "quarterly") == []


def test_remaining_periods():
    # Phase ends 2028-Q2, project ends 2033-Q2 → 20 quarters remaining (QGR).
    assert cf_pool.remaining_periods(date(2033, 6, 30), date(2028, 6, 30), "quarterly") == 20
    # Final phase (ends in the project's last bucket) → 0.
    assert cf_pool.remaining_periods(date(2030, 12, 31), date(2030, 11, 1), "quarterly") == 0
    # Missing dates / unsupported frequency → None (like the cycle count).
    assert cf_pool.remaining_periods(None, date(2030, 1, 1), "quarterly") is None
    assert cf_pool.remaining_periods(date(2033, 1, 1), date(2030, 1, 1), "weekly") is None
