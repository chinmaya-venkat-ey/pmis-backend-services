"""Carry-forward (full-leftover, phase|milestone equal split) + per-activity split.

Covers:
  * payment_calc.carry_forward_distribution — phase-wise (equal per subsequent
    phase, compounding) and milestone-wise (equal per subsequent milestone; a
    phase's inflow is proportional to its milestone count, weightages untouched).
  * CarryForwardUpdateRequest validation (mode required + restricted).
  * _build_term_activities — even-split default, stored-allocation override,
    display code, no leftover nulls.
  * PaymentPageService set_carry_forward / set_payment_term_activities guards.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.errors import ValidationError
from app.schemas.payment import CarryForwardUpdateRequest, OneTimeUpdateRequest
from app.services import payment_page_service as pps
from app.services.payment_page_service import (
    PaymentPageService, _build_term_activities, _even_split,
    _last_phase_percent_overrides, _phase_order_key,
)
from app.utilities import payment_calc


def _cost(phase, cost, code="fixed", tax=0):
    return SimpleNamespace(cost_type_code=code, phase=phase, cost=Decimal(str(cost)),
                           tax_amount=Decimal(str(tax)))


def _term(phase, percent, milestone_id):
    return SimpleNamespace(phase=phase, percent_of_payment=Decimal(str(percent)),
                           milestone_id=milestone_id)


# ------------------------------------------------- carry_forward_distribution

def test_phase_wise_splits_equally_across_all_subsequent_phases():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost("3", 5000)]
    term_rows = [_term("1", 45, "m1")]  # leftover phase 1 = 10000 - 4500 = 5500
    cfg = {"1": {"enabled": True, "mode": "phase"}}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)
    # 5500 split equally across phases 2 and 3 -> 2750 each
    assert cf["phase_received"] == {"1": Decimal("0.00"), "2": Decimal("2750.00"), "3": Decimal("2750.00")}
    assert cf["effective_base"]["2"] == Decimal("22750.00")
    assert cf["effective_base"]["3"] == Decimal("7750.00")
    assert cf["carried_out"]["1"] == Decimal("5500.00")
    assert cf["milestone_received"] == {}


def test_phase_wise_compounds_down_the_chain():
    cost_rows = [_cost("1", 10000), _cost("2", 0), _cost("3", 0)]
    term_rows = [_term("1", 0, "m1")]  # leftover phase 1 = 10000
    cfg = {"1": {"enabled": True, "mode": "phase"}, "2": {"enabled": True, "mode": "phase"}}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)
    # p1 -> 5000 each to p2,p3. p2 now has 5000 leftover, carries all to p3.
    assert cf["phase_received"]["2"] == Decimal("5000.00")
    assert cf["effective_base"]["2"] == Decimal("5000.00")
    assert cf["phase_received"]["3"] == Decimal("10000.00")  # 5000 from p1 + 5000 from p2


def test_milestone_wise_phase_inflow_is_proportional_to_milestone_count():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost("3", 5000)]
    term_rows = [
        _term("1", 45, "m1"),                 # leftover phase 1 = 5500
        _term("2", 30, "m2a"), _term("2", 20, "m2b"),  # phase 2 has 2 milestones
        _term("3", 50, "m3"),                 # phase 3 has 1 milestone
    ]
    cfg = {"1": {"enabled": True, "mode": "milestone"}}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)
    # 5500 split equally across the 3 subsequent milestones (m2a, m2b, m3)
    mr = cf["milestone_received"]
    assert mr["m2a"] == Decimal("1833.33")
    assert mr["m2b"] == Decimal("1833.33")
    assert mr["m3"] == Decimal("1833.34")    # last absorbs the remainder
    assert sum(mr.values()) == Decimal("5500.00")
    # phase 2 (2 milestones) receives ~2x phase 3 (1 milestone)
    p2_inflow = mr["m2a"] + mr["m2b"]
    assert p2_inflow == Decimal("3666.66")
    assert mr["m3"] == Decimal("1833.34")
    # weightages untouched: milestone_received does NOT enter the phase % base
    assert cf["effective_base"]["2"] == Decimal("20000.00")
    assert cf["phase_received"]["2"] == Decimal("0.00")


def test_one_time_no_longer_auto_folds_without_allocation():
    # one-time is distributed via one_time_distribution now, not auto-folded here.
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost(None, 3000, code="one_time")]
    cf = payment_calc.carry_forward_distribution(cost_rows, [], ["1", "2"], {})
    assert cf["effective_base"]["1"] == Decimal("10000.00")
    assert cf["effective_base"]["2"] == Decimal("20000.00")


def test_one_time_distribution_last_phase_absorbs_by_default():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost(None, 3000, code="one_time")]
    alloc = payment_calc.one_time_distribution(cost_rows, ["1", "2"], {})
    assert alloc == {"1": Decimal("0.00"), "2": Decimal("3000.00")}  # last phase = remainder


def test_one_time_distribution_explicit_shares_plus_remainder():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost("3", 5000),
                 _cost(None, 10000, code="one_time")]
    cfg = {"1": {"enabled": True, "mode": "amount", "value": Decimal("4000")},
           "2": {"enabled": True, "mode": "percent", "value": Decimal("20")}}  # 20% of 10000
    alloc = payment_calc.one_time_distribution(cost_rows, ["1", "2", "3"], cfg)
    assert alloc["1"] == Decimal("4000.00")
    assert alloc["2"] == Decimal("2000.00")
    assert alloc["3"] == Decimal("4000.00")            # last absorbs 10000 − 6000
    assert sum(alloc.values()) == Decimal("10000.00")  # fully utilised


def test_carry_forward_base_includes_one_time_alloc():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost(None, 3000, code="one_time")]
    alloc = {"1": Decimal("3000.00"), "2": Decimal("0.00")}
    cf = payment_calc.carry_forward_distribution(cost_rows, [], ["1", "2"], {}, one_time_alloc=alloc)
    assert cf["effective_base"]["1"] == Decimal("13000.00")   # 10000 fixed + 3000 one-time
    assert cf["effective_base"]["2"] == Decimal("20000.00")


def test_one_time_request_validation():
    with pytest.raises(Exception):
        OneTimeUpdateRequest(enabled=True)                                  # mode+value required
    with pytest.raises(Exception):
        OneTimeUpdateRequest(enabled=True, mode="percent")                  # value required
    with pytest.raises(Exception):
        OneTimeUpdateRequest(enabled=True, mode="bad", value=Decimal("10"))  # bad mode
    with pytest.raises(Exception):
        OneTimeUpdateRequest(enabled=True, mode="percent", value=Decimal("150"))  # >100
    assert OneTimeUpdateRequest(enabled=True, mode="amount", value=Decimal("5000")).value == Decimal("5000")
    d = OneTimeUpdateRequest(enabled=False, mode="percent", value=Decimal("30"))
    assert d.mode is None and d.value is None                                # disabled clears


# ----------------------------------------- custom + time-based (formula-driven)

def _cf_cfg(method, formula, recipient_vars):
    return {"enabled": True, "method": method, "formula": formula,
            "recipient_vars": recipient_vars}


def test_phase_custom_splits_by_recipient_percent():
    cost_rows = [_cost("1", 10000), _cost("2", 0), _cost("3", 0)]
    term_rows = [_term("1", 0, "m1")]  # leftover phase 1 = 10000
    cfg = {"1": _cf_cfg("phase", "leftover * recipientPercent / 100", {
        "2": {"recipientPercent": Decimal("70")},
        "3": {"recipientPercent": Decimal("30")},
    })}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)
    assert cf["phase_received"]["2"] == Decimal("7000.00")
    assert cf["phase_received"]["3"] == Decimal("3000.00")
    assert cf["carried_out"]["1"] == Decimal("10000.00")


def test_phase_custom_zero_share_recipient_gets_nothing():
    cost_rows = [_cost("1", 10000), _cost("2", 0), _cost("3", 0)]
    term_rows = [_term("1", 0, "m1")]
    cfg = {"1": _cf_cfg("phase", "leftover * recipientPercent / 100", {
        "2": {"recipientPercent": Decimal("100")},
        "3": {"recipientPercent": Decimal("0")},
    })}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)
    assert cf["phase_received"]["2"] == Decimal("10000.00")
    assert cf["phase_received"]["3"] == Decimal("0.00")     # explicit 0 stays 0


def test_time_splits_proportional_to_recipient_cycles():
    cost_rows = [_cost("1", 9000), _cost("2", 0), _cost("3", 0)]
    term_rows = [_term("1", 0, "m1")]  # leftover 9000
    cfg = {"1": _cf_cfg("time", "leftover * recipientCycles / totalCycles", {
        "2": {"recipientCycles": Decimal("2"), "totalCycles": Decimal("3")},
        "3": {"recipientCycles": Decimal("1"), "totalCycles": Decimal("3")},
    })}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)
    assert cf["phase_received"]["2"] == Decimal("6000.00")  # 2/3 of 9000
    assert cf["phase_received"]["3"] == Decimal("3000.00")  # 1/3 of 9000
    assert cf["carried_out"]["1"] == Decimal("9000.00")


def test_custom_all_zero_recipients_carries_nothing():
    # Fully-stale custom config (every recipient 0%) -> nothing dumped anywhere;
    # the leftover stays with the carrying phase.
    cost_rows = [_cost("1", 10000), _cost("2", 0), _cost("3", 0)]
    term_rows = [_term("1", 0, "m1")]  # leftover 10000
    cfg = {"1": _cf_cfg("phase", "leftover * recipientPercent / 100", {
        "2": {"recipientPercent": Decimal("0")},
        "3": {"recipientPercent": Decimal("0")},
    })}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)
    assert cf["phase_received"]["2"] == Decimal("0.00")
    assert cf["phase_received"]["3"] == Decimal("0.00")
    assert cf["carried_out"]["1"] == Decimal("0.00")


# ------------------------- custom re-normalisation (stale-after-reorder) -----

def test_cf_recipient_vars_renormalises_stale_custom():
    # Carrying from 'A' (idx 0); subsequent = [B, C]. A 3rd recipient dropped out
    # of "subsequent" after a reorder, so the stored shares now sum to 80 — they
    # are scaled back to 100 (50/30 -> 62.5/37.5), not dumped on the last one.
    svc = PaymentPageService(MagicMock())
    alloc_map = {"B": SimpleNamespace(percent=Decimal("50")),
                 "C": SimpleNamespace(percent=Decimal("30"))}
    out = svc._build_cf_recipient_vars("phase", "custom", 0, ["A", "B", "C"], {}, {}, alloc_map)
    assert out["B"]["recipientPercent"] == Decimal("62.5")
    assert out["C"]["recipientPercent"] == Decimal("37.5")


def test_cf_recipient_vars_custom_noop_when_full():
    svc = PaymentPageService(MagicMock())
    alloc_map = {"B": SimpleNamespace(percent=Decimal("60")),
                 "C": SimpleNamespace(percent=Decimal("40"))}
    out = svc._build_cf_recipient_vars("phase", "custom", 0, ["A", "B", "C"], {}, {}, alloc_map)
    assert out["B"]["recipientPercent"] == Decimal("60")
    assert out["C"]["recipientPercent"] == Decimal("40")


# ------------------------------------------------- CarryForwardUpdateRequest

def test_cf_request_requires_method_when_enabled():
    with pytest.raises(Exception):
        CarryForwardUpdateRequest(enabled=True)


def test_cf_request_rejects_unknown_mode_alias():
    with pytest.raises(Exception):
        CarryForwardUpdateRequest(enabled=True, mode="amount")


def test_cf_request_accepts_method_code():
    assert CarryForwardUpdateRequest(
        enabled=True, method_code="phase_evenly").method_code == "phase_evenly"
    assert CarryForwardUpdateRequest(
        enabled=True, method_code="milestone_evenly").method_code == "milestone_evenly"


def test_cf_request_legacy_mode_folds_into_method_code():
    assert CarryForwardUpdateRequest(enabled=True, mode="phase").method_code == "phase_evenly"
    assert CarryForwardUpdateRequest(
        enabled=True, mode="milestone").method_code == "milestone_evenly"


def test_cf_request_disabled_clears_method_code():
    assert CarryForwardUpdateRequest(enabled=False, mode="phase").method_code is None
    assert CarryForwardUpdateRequest(
        enabled=False, method_code="phase_evenly").method_code is None


# --------------------------------------------- last-phase auto-utilise (even split)

def _pterm(tid, phase, percent):
    return SimpleNamespace(id=tid, phase=phase,
                           percent_of_payment=None if percent is None else Decimal(str(percent)))


def test_even_split_sums_exactly():
    assert _even_split(Decimal("100"), 2) == [Decimal("50.00"), Decimal("50.00")]
    three = _even_split(Decimal("100"), 3)
    assert sum(three) == Decimal("100.00") and three == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]


def test_last_phase_even_split_when_all_null():
    terms = [_pterm("a", "1", 30), _pterm("b", "3", None), _pterm("c", "3", None)]
    ov = _last_phase_percent_overrides(["1", "2", "3"], terms)
    assert ov == {"b": Decimal("50.00"), "c": Decimal("50.00")}  # last phase (3), both null


def test_last_phase_fills_remaining_when_partially_explicit():
    # 60% explicit + one null → null fills the remaining 40% (phase totals 100%)
    terms = [_pterm("b", "3", 60), _pterm("c", "3", None)]
    assert _last_phase_percent_overrides(["1", "2", "3"], terms) == {"c": Decimal("40.00")}


def test_last_phase_fills_remaining_split_across_nulls():
    # 50% explicit + two nulls → split the remaining 50% evenly → 25% each
    terms = [_pterm("a", "3", 50), _pterm("b", "3", None), _pterm("c", "3", None)]
    assert _last_phase_percent_overrides(["1", "2", "3"], terms) == {
        "b": Decimal("25.00"), "c": Decimal("25.00")}


def test_last_phase_no_fill_when_all_explicit():
    # nothing null to fill — explicit values stand as-is
    terms = [_pterm("b", "3", 60), _pterm("c", "3", 30)]
    assert _last_phase_percent_overrides(["1", "2", "3"], terms) == {}


def test_non_last_phase_never_overridden():
    terms = [_pterm("a", "1", None), _pterm("b", "1", None), _pterm("c", "3", 100)]
    # phase 1 (non-last) is all-null but must NOT be auto-split; phase 3 explicit → no override
    assert _last_phase_percent_overrides(["1", "2", "3"], terms) == {}


# ----------------------------------------------------------- phase ordering

def _dt(s):
    from datetime import datetime
    return datetime.fromisoformat(s)


def test_phase_order_by_start_then_shorter_span_then_undated_last():
    # a & b share a start; a has the earlier end (shorter span) -> a precedes b.
    # c starts later. d has no dates -> sorts last.
    dates = {
        "a": (_dt("2025-01-01"), _dt("2025-03-01")),
        "b": (_dt("2025-01-01"), _dt("2025-06-01")),
        "c": (_dt("2025-04-01"), _dt("2025-05-01")),
        "d": (None, None),
    }
    ordered = sorted(["d", "c", "b", "a"], key=lambda p: _phase_order_key(p, dates))
    assert ordered == ["a", "b", "c", "d"]


def test_phase_order_ignores_insertion_and_name():
    # '10' starts before '2' -> chronology wins over numeric name / insertion.
    dates = {
        "10": (_dt("2025-01-01"), _dt("2025-02-01")),
        "2": (_dt("2025-05-01"), _dt("2025-06-01")),
    }
    assert sorted(["2", "10"], key=lambda p: _phase_order_key(p, dates)) == ["10", "2"]


# --------------------------------------------------------- term activities

def test_build_term_activities_even_split_default_and_display_code():
    acts = [SimpleNamespace(id="a1", name="A1", position=1),
            SimpleNamespace(id="a2", name="A2", position=2),
            SimpleNamespace(id="a3", name="A3", position=3)]
    out = _build_term_activities(Decimal("10000"), acts, [], term_percent=Decimal("45"),
                                 milestone_position=3)
    # 45 split evenly -> 15/15/15, summing to 45 exactly; no nulls
    assert [a.percent_of_payment for a in out] == [Decimal("15.00"), Decimal("15.00"), Decimal("15.00")]
    assert out[0].activity_display_code == "A3.1"
    assert out[1].value == Decimal("1500.00")     # 15% of 10000
    assert all(a.percent_of_payment is not None for a in out)


def test_build_term_activities_stored_allocations_override_even_split():
    acts = [SimpleNamespace(id="a1", name="A1", position=1),
            SimpleNamespace(id="a2", name="A2", position=2)]
    allocs = [SimpleNamespace(activity_id="a1", percent_of_payment=Decimal("30"))]
    out = _build_term_activities(Decimal("10000"), acts, allocs, term_percent=Decimal("45"),
                                 milestone_position=3)
    by_id = {a.activity_id: a for a in out}
    assert by_id["a1"].percent_of_payment == Decimal("30")   # stored
    assert by_id["a2"].percent_of_payment is None            # unallocated (no even split when stored)


# --------------------------------------------------- set_carry_forward (svc)

_CF_METHODS = {
    "phase_evenly": ("phase", "evenly", "leftover / numRecipients"),
    "milestone_evenly": ("milestone", "evenly", "leftover / numRecipients"),
    "phase_custom": ("phase", "custom", "leftover * recipientPercent / 100"),
    "time_quarterly": ("time", "quarterly", "leftover * recipientCycles / totalCycles"),
}


def _svc(monkeypatch, ordered, term_rows=None, *, freq="quarterly", phase_dates=None):
    svc = PaymentPageService(MagicMock())
    svc._require_project = MagicMock(
        return_value=SimpleNamespace(id="p1", payment_frequency_code=freq))
    svc.ensure_phase_configs = MagicMock()
    svc.build_page = MagicMock(return_value="PAGE")
    svc.audit = MagicMock()
    svc.phase_qrg = MagicMock()
    svc.cf_allocations = MagicMock()
    svc.cost_items = MagicMock()
    svc.cost_items.phase_milestone_date_bounds = MagicMock(return_value=phase_dates or {})
    svc._load_phase_state = MagicMock(
        return_value=(ordered, {p: SimpleNamespace(id=f"cfg{p}") for p in ordered},
                      {"leftover": {p: Decimal("1000.00") for p in ordered}}, [], term_rows or []),
    )
    # Stub the masters catalog + method resolver so the guard logic runs without a DB.
    monkeypatch.setattr(pps, "assert_payment_writable", lambda *a, **k: None)
    monkeypatch.setattr(
        pps.catalogs, "is_known_carry_forward_method",
        lambda db, code: code in _CF_METHODS,
    )
    svc._resolve_cf_method = lambda code: _CF_METHODS.get(code, (None, None, None))
    return svc


def test_set_cf_phase_wise_rejects_last_phase(monkeypatch):
    svc = _svc(monkeypatch, ["1", "2"])
    with pytest.raises(ValidationError):
        svc.set_carry_forward("p1", "2", enabled=True, method_code="phase_evenly", caller_user_id="u1")


def test_set_cf_milestone_wise_rejects_no_subsequent_milestones(monkeypatch):
    # phase 1 carrying milestone-wise, but phase 2 has no terms/milestones
    svc = _svc(monkeypatch, ["1", "2"], term_rows=[_term("1", 45, "m1")])
    with pytest.raises(ValidationError):
        svc.set_carry_forward("p1", "1", enabled=True, method_code="milestone_evenly", caller_user_id="u1")


def test_set_cf_rejects_unknown_method(monkeypatch):
    svc = _svc(monkeypatch, ["1", "2"])
    with pytest.raises(ValidationError):
        svc.set_carry_forward("p1", "1", enabled=True, method_code="amount", caller_user_id="u1")


def test_set_cf_time_rejects_when_no_cycles(monkeypatch):
    # time method needs dated subsequent phases; empty date bounds -> 0 cycles.
    svc = _svc(monkeypatch, ["1", "2"], phase_dates={})
    with pytest.raises(ValidationError):
        svc.set_carry_forward("p1", "1", enabled=True, method_code="time_quarterly", caller_user_id="u1")


def test_set_cf_custom_requires_full_allocation(monkeypatch):
    # phase_custom across subsequent phase "2" — 60% does not fully allocate.
    svc = _svc(monkeypatch, ["1", "2"])
    with pytest.raises(ValidationError):
        svc.set_carry_forward(
            "p1", "1", enabled=True, method_code="phase_custom",
            allocation_mode="percent", allocations=[{"recipient_key": "2", "value": Decimal("60")}],
            caller_user_id="u1")


def test_set_cf_custom_persists_when_fully_allocated(monkeypatch):
    svc = _svc(monkeypatch, ["1", "2"])
    out = svc.set_carry_forward(
        "p1", "1", enabled=True, method_code="phase_custom",
        allocation_mode="percent", allocations=[{"recipient_key": "2", "value": Decimal("100")}],
        caller_user_id="u1")
    assert out == "PAGE"
    svc.cf_allocations.replace_for_phase.assert_called_once()


def test_set_cf_persists_when_valid(monkeypatch):
    svc = _svc(monkeypatch, ["1", "2"])
    out = svc.set_carry_forward("p1", "1", enabled=True, method_code="phase_evenly", caller_user_id="u1")
    assert out == "PAGE"
    svc.phase_qrg.update.assert_called_once()


# --------------------------------------------- set_payment_term_activities (svc)

def _term_svc(monkeypatch, *, term_pct="45", ptype="partial_payment"):
    svc = PaymentPageService(MagicMock())
    term = SimpleNamespace(id="t1", project_id="p1", milestone_id="m1",
                           percent_of_payment=Decimal(term_pct), phase="1",
                           cost_item_id="c1", frequency_code=None)
    svc.payment_terms = MagicMock()
    svc.payment_terms.get_by_id = MagicMock(return_value=term)
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1"))
    svc.milestones = MagicMock()
    svc.milestones.payment_type_by_ids = MagicMock(return_value={"m1": ptype})
    svc.activities = MagicMock()
    svc.activities.list_by_milestone_ids = MagicMock(return_value={
        "m1": [SimpleNamespace(id="a1", name="A1", position=1),
               SimpleNamespace(id="a2", name="A2", position=2)],
    })
    svc.term_activities = MagicMock()
    svc.audit = MagicMock()
    svc._single_term_response = MagicMock(return_value="TERM")
    monkeypatch.setattr(pps, "assert_payment_writable", lambda *a, **k: None)
    return svc


def test_term_activities_sum_must_equal_term_percent(monkeypatch):
    svc = _term_svc(monkeypatch, term_pct="45")
    with pytest.raises(ValidationError):
        svc.set_payment_term_activities(
            "t1", [{"activity_id": "a1", "percent_of_payment": Decimal("10")},
                   {"activity_id": "a2", "percent_of_payment": Decimal("20")}],
            caller_user_id="u1")


def test_term_activities_persists_when_sum_matches(monkeypatch):
    svc = _term_svc(monkeypatch, term_pct="45")
    out = svc.set_payment_term_activities(
        "t1", [{"activity_id": "a1", "percent_of_payment": Decimal("20")},
               {"activity_id": "a2", "percent_of_payment": Decimal("25")}],
        caller_user_id="u1")
    assert out == "TERM"
    svc.term_activities.replace_for_term.assert_called_once()
