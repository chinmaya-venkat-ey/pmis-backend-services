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
from app.schemas.payment import CarryForwardUpdateRequest
from app.services import payment_page_service as pps
from app.services.payment_page_service import PaymentPageService, _build_term_activities, _seq_key
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


def test_one_time_folds_into_first_phase_by_sequence():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost(None, 3000, code="one_time")]
    cf = payment_calc.carry_forward_distribution(cost_rows, [], ["1", "2"], {})
    assert cf["effective_base"]["1"] == Decimal("13000.00")
    assert cf["effective_base"]["2"] == Decimal("20000.00")


# ------------------------------------------------- CarryForwardUpdateRequest

def test_cf_request_requires_mode_when_enabled():
    with pytest.raises(Exception):
        CarryForwardUpdateRequest(enabled=True)


def test_cf_request_rejects_unknown_mode():
    with pytest.raises(Exception):
        CarryForwardUpdateRequest(enabled=True, mode="amount")


def test_cf_request_accepts_phase_and_milestone():
    assert CarryForwardUpdateRequest(enabled=True, mode="phase").mode == "phase"
    assert CarryForwardUpdateRequest(enabled=True, mode="milestone").mode == "milestone"


def test_cf_request_disabled_clears_mode():
    assert CarryForwardUpdateRequest(enabled=False, mode="phase").mode is None


# ----------------------------------------------------------- phase ordering

def test_seq_key_numeric_names_sort_numerically():
    assert sorted(["2", "10", "1"], key=lambda p: _seq_key(p, None)) == ["1", "2", "10"]


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

def _svc(monkeypatch, ordered, term_rows=None):
    svc = PaymentPageService(MagicMock())
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1"))
    svc.ensure_phase_configs = MagicMock()
    svc.build_page = MagicMock(return_value="PAGE")
    svc.audit = MagicMock()
    svc.phase_qrg = MagicMock()
    svc._load_phase_state = MagicMock(
        return_value=(ordered, {p: SimpleNamespace(id=f"cfg{p}") for p in ordered},
                      {"leftover": {}}, [], term_rows or []),
    )
    monkeypatch.setattr(pps, "assert_payment_writable", lambda *a, **k: None)
    return svc


def test_set_cf_phase_wise_rejects_last_phase(monkeypatch):
    svc = _svc(monkeypatch, ["1", "2"])
    with pytest.raises(ValidationError):
        svc.set_carry_forward("p1", "2", enabled=True, mode="phase", caller_user_id="u1")


def test_set_cf_milestone_wise_rejects_no_subsequent_milestones(monkeypatch):
    # phase 1 carrying milestone-wise, but phase 2 has no terms/milestones
    svc = _svc(monkeypatch, ["1", "2"], term_rows=[_term("1", 45, "m1")])
    with pytest.raises(ValidationError):
        svc.set_carry_forward("p1", "1", enabled=True, mode="milestone", caller_user_id="u1")


def test_set_cf_rejects_unknown_mode(monkeypatch):
    svc = _svc(monkeypatch, ["1", "2"])
    with pytest.raises(ValidationError):
        svc.set_carry_forward("p1", "1", enabled=True, mode="amount", caller_user_id="u1")


def test_set_cf_persists_when_valid(monkeypatch):
    svc = _svc(monkeypatch, ["1", "2"])
    out = svc.set_carry_forward("p1", "1", enabled=True, mode="phase", caller_user_id="u1")
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
