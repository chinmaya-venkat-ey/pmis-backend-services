"""OPE (one-time) allocation guide — payment_calc.one_time_allocation_summary.

This is the pre-validate/publish guide shown on the payment page totals: how
much of the one-time pool the user has EXPLICITLY allocated to phases vs. how
much is still PENDING (must reach 0 to publish). It is an allocation figure, not
a billing/utilisation figure — the auto-absorbed last-phase remainder counts as
pending, never as allocated.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.utilities import payment_calc as pc


def _cost(code, phase=None, cost=0, tax=0):
    return SimpleNamespace(cost_type_code=code, phase=phase,
                           cost=Decimal(str(cost)), tax_amount=Decimal(str(tax)))


def _ot(enabled, mode=None, value=None):
    return {"enabled": enabled, "mode": mode, "value": value}


def test_no_ope_pool_is_all_zero():
    rows = [_cost("fixed", "1", 10000)]
    s = pc.one_time_allocation_summary(rows, ["1"], {})
    assert s == {"pool": Decimal("0.00"), "allocated": Decimal("0.00"),
                 "pending": Decimal("0.00")}


def test_nothing_allocated_all_pending():
    # 100k OPE, two phases, neither opts in → the last phase auto-absorbs the
    # whole pool, so it is ALL pending (nothing explicitly allocated yet).
    rows = [_cost("one_time", cost=100000), _cost("fixed", "1", 10000),
            _cost("fixed", "2", 10000)]
    s = pc.one_time_allocation_summary(rows, ["1", "2"], {})
    assert s["pool"] == Decimal("100000.00")
    assert s["allocated"] == Decimal("0.00")
    assert s["pending"] == Decimal("100000.00")


def test_partial_percent_allocation_65_35():
    # 100k OPE; phase 1 explicitly takes 65% → 65k allocated, 35k pending.
    rows = [_cost("one_time", cost=100000), _cost("fixed", "1", 10000),
            _cost("fixed", "2", 10000)]
    cfg = {"1": _ot(True, "percent", 65)}
    s = pc.one_time_allocation_summary(rows, ["1", "2"], cfg)
    assert s["allocated"] == Decimal("65000.00")
    assert s["pending"] == Decimal("35000.00")


def test_amount_mode_allocation():
    rows = [_cost("one_time", cost=100000), _cost("fixed", "1", 10000),
            _cost("fixed", "2", 10000)]
    cfg = {"1": _ot(True, "amount", 40000)}
    s = pc.one_time_allocation_summary(rows, ["1", "2"], cfg)
    assert s["allocated"] == Decimal("40000.00")
    assert s["pending"] == Decimal("60000.00")


def test_last_phase_opt_in_is_ignored_and_stays_pending():
    # Only the LAST phase opts in — it always auto-absorbs the remainder, so its
    # explicit share is not counted: allocated stays 0, all pending.
    rows = [_cost("one_time", cost=100000), _cost("fixed", "1", 10000),
            _cost("fixed", "2", 10000)]
    cfg = {"2": _ot(True, "percent", 100)}
    s = pc.one_time_allocation_summary(rows, ["1", "2"], cfg)
    assert s["allocated"] == Decimal("0.00")
    assert s["pending"] == Decimal("100000.00")


def test_multiple_non_last_phases_accumulate():
    rows = [_cost("one_time", cost=100000), _cost("fixed", "1", 1),
            _cost("fixed", "2", 1), _cost("fixed", "3", 1)]
    cfg = {"1": _ot(True, "percent", 30), "2": _ot(True, "amount", 25000)}
    s = pc.one_time_allocation_summary(rows, ["1", "2", "3"], cfg)
    assert s["allocated"] == Decimal("55000.00")   # 30k + 25k
    assert s["pending"] == Decimal("45000.00")


def test_over_allocation_is_clamped_to_pool():
    rows = [_cost("one_time", cost=100000), _cost("fixed", "1", 1),
            _cost("fixed", "2", 1), _cost("fixed", "3", 1)]
    cfg = {"1": _ot(True, "percent", 80), "2": _ot(True, "percent", 80)}
    s = pc.one_time_allocation_summary(rows, ["1", "2", "3"], cfg)
    # 80k then clamped to remaining 20k → 100k allocated, 0 pending.
    assert s["allocated"] == Decimal("100000.00")
    assert s["pending"] == Decimal("0.00")


def test_recurring_only_phase_excluded_from_eligible():
    # Phase 3 is recurring-only → outside the billing sequence; phase 2 becomes
    # the last eligible (auto-absorb) phase, phase 1's 65% is the allocation.
    rows = [_cost("one_time", cost=100000), _cost("fixed", "1", 10000),
            _cost("fixed", "2", 10000), _cost("recurring_cost", "3", 5000)]
    cfg = {"1": _ot(True, "percent", 65)}
    s = pc.one_time_allocation_summary(rows, ["1", "2", "3"], cfg)
    assert s["allocated"] == Decimal("65000.00")
    assert s["pending"] == Decimal("35000.00")
