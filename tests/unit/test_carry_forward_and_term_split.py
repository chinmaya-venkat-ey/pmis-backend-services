"""Carry-forward (ex-QRG) distribution + per-activity payment-term split.

Covers:
  * payment_calc.carry_forward_distribution — compounding down the phase chain,
    percent-of-leftover and flat-amount modes, amount clamped to leftover, the
    last phase never carries.
  * CarryForwardUpdateRequest validation — XOR of percent/amount, mode
    inference, disabled clears the values.
  * PaymentPageService phase ordering (_seq_key), per-activity builder, and the
    set_carry_forward / set_payment_term_activities validations.
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


def _term(phase, percent):
    return SimpleNamespace(phase=phase, percent_of_payment=Decimal(str(percent)))


# ----------------------------------------------------- carry_forward_distribution

def test_carry_forward_compounds_down_the_chain():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost("3", 5000)]
    term_rows = [_term("1", 50)]  # phase 1 allocates 5000 -> leftover 5000
    cfg = {
        "1": {"enabled": True, "mode": "percent", "percent": Decimal("100"), "amount": None},
        "2": {"enabled": True, "mode": "amount", "percent": None, "amount": Decimal("10000")},
        "3": {"enabled": True, "mode": "percent", "percent": Decimal("100"), "amount": None},
    }
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2", "3"], cfg)

    assert cf["received"] == {"1": Decimal("0.00"), "2": Decimal("5000.00"), "3": Decimal("10000.00")}
    assert cf["effective_base"]["2"] == Decimal("25000.00")   # 20000 + 5000 received
    assert cf["effective_base"]["3"] == Decimal("15000.00")   # 5000 + 10000 received
    assert cf["leftover"]["2"] == Decimal("25000.00")
    assert cf["carried_out"]["1"] == Decimal("5000.00")
    assert cf["carried_out"]["2"] == Decimal("10000.00")
    # phase 3 is last -> never carries, even though enabled.
    assert cf["carried_out"]["3"] == Decimal("0.00")


def test_carry_forward_amount_clamped_to_leftover():
    cost_rows = [_cost("1", 10000), _cost("2", 5000)]
    term_rows = [_term("1", 50)]  # leftover phase 1 = 5000
    cfg = {"1": {"enabled": True, "mode": "amount", "percent": None, "amount": Decimal("999999")}}
    cf = payment_calc.carry_forward_distribution(cost_rows, term_rows, ["1", "2"], cfg)
    assert cf["carried_out"]["1"] == Decimal("5000.00")       # clamped to leftover
    assert cf["received"]["2"] == Decimal("5000.00")


def test_carry_forward_one_time_folds_into_first_phase():
    cost_rows = [_cost("1", 10000), _cost("2", 20000), _cost(None, 3000, code="one_time")]
    cf = payment_calc.carry_forward_distribution(cost_rows, [], ["1", "2"], {})
    assert cf["effective_base"]["1"] == Decimal("13000.00")   # 10000 + 3000 one-time
    assert cf["effective_base"]["2"] == Decimal("20000.00")


def test_carry_forward_disabled_phase_does_not_carry():
    cost_rows = [_cost("1", 10000), _cost("2", 5000)]
    cf = payment_calc.carry_forward_distribution(cost_rows, [], ["1", "2"], {})
    assert cf["carried_out"]["1"] == Decimal("0.00")
    assert cf["received"]["2"] == Decimal("0.00")


# ------------------------------------------------- CarryForwardUpdateRequest

def test_cf_request_infers_percent_mode():
    req = CarryForwardUpdateRequest(enabled=True, percent=Decimal("50"))
    assert req.mode == "percent" and req.amount is None


def test_cf_request_infers_amount_mode():
    req = CarryForwardUpdateRequest(enabled=True, amount=Decimal("100"))
    assert req.mode == "amount" and req.percent is None


def test_cf_request_rejects_both():
    with pytest.raises(Exception):
        CarryForwardUpdateRequest(enabled=True, percent=Decimal("50"), amount=Decimal("100"))


def test_cf_request_rejects_neither_when_enabled():
    with pytest.raises(Exception):
        CarryForwardUpdateRequest(enabled=True)


def test_cf_request_disabled_clears_values():
    req = CarryForwardUpdateRequest(enabled=False, percent=Decimal("50"), amount=Decimal("9"))
    assert req.mode is None and req.percent is None and req.amount is None


# ----------------------------------------------------------- phase ordering

def test_seq_key_numeric_names_sort_numerically_not_lexically():
    phases = ["2", "10", "1"]
    ordered = sorted(phases, key=lambda p: _seq_key(p, None))
    assert ordered == ["1", "2", "10"]


def test_seq_key_explicit_sequence_wins():
    cfg10 = SimpleNamespace(sequence=0)
    # phase "10" forced to sequence 0 sorts before numeric "1"/"2".
    ordered = sorted(["1", "2", "10"], key=lambda p: _seq_key(p, cfg10 if p == "10" else None))
    assert ordered[0] == "10"


# --------------------------------------------------------- term activities

def test_build_term_activities_maps_percent_and_value():
    acts = [SimpleNamespace(id="a1", name="A1"), SimpleNamespace(id="a2", name="A2")]
    allocs = [SimpleNamespace(activity_id="a1", percent_of_payment=Decimal("10"))]
    out = _build_term_activities(Decimal("1000"), acts, allocs)
    assert out[0].activity_id == "a1" and out[0].value == Decimal("100.00")
    assert out[1].percent_of_payment is None and out[1].value == Decimal("0.00")


# --------------------------------------------------- set_carry_forward (svc)

def _svc(monkeypatch):
    svc = PaymentPageService(MagicMock())
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1"))
    svc.ensure_phase_configs = MagicMock()
    svc.build_page = MagicMock(return_value="PAGE")
    svc.audit = MagicMock()
    svc.phase_qrg = MagicMock()
    monkeypatch.setattr(pps, "assert_payment_writable", lambda *a, **k: None)
    return svc


def test_set_carry_forward_rejects_last_phase(monkeypatch):
    svc = _svc(monkeypatch)
    svc._load_phase_state = MagicMock(return_value=(["1", "2"], {}, {"leftover": {}}, [], []))
    with pytest.raises(ValidationError):
        svc.set_carry_forward(
            "p1", "2", enabled=True, mode="amount", percent=None,
            amount=Decimal("10"), caller_user_id="u1",
        )


def test_set_carry_forward_rejects_amount_over_leftover(monkeypatch):
    svc = _svc(monkeypatch)
    svc._load_phase_state = MagicMock(
        return_value=(["1", "2"], {}, {"leftover": {"1": Decimal("100")}}, [], []),
    )
    with pytest.raises(ValidationError):
        svc.set_carry_forward(
            "p1", "1", enabled=True, mode="amount", percent=None,
            amount=Decimal("200"), caller_user_id="u1",
        )


def test_set_carry_forward_persists_when_valid(monkeypatch):
    svc = _svc(monkeypatch)
    svc._load_phase_state = MagicMock(
        return_value=(["1", "2"], {"1": SimpleNamespace(id="cfg1")},
                      {"leftover": {"1": Decimal("100")}}, [], []),
    )
    out = svc.set_carry_forward(
        "p1", "1", enabled=True, mode="amount", percent=None,
        amount=Decimal("50"), caller_user_id="u1",
    )
    assert out == "PAGE"
    svc.phase_qrg.update.assert_called_once()


# --------------------------------------------- set_payment_term_activities (svc)

def _term_svc(monkeypatch, *, term_pct="45", ptype="partial_payment"):
    svc = PaymentPageService(MagicMock())
    term = SimpleNamespace(
        id="t1", project_id="p1", milestone_id="m1",
        percent_of_payment=Decimal(term_pct), phase="1", cost_item_id="c1",
        frequency_code=None,
    )
    svc.payment_terms = MagicMock()
    svc.payment_terms.get_by_id = MagicMock(return_value=term)
    svc._require_project = MagicMock(return_value=SimpleNamespace(id="p1"))
    svc.milestones = MagicMock()
    svc.milestones.payment_type_by_ids = MagicMock(return_value={"m1": ptype})
    svc.activities = MagicMock()
    svc.activities.list_by_milestone_ids = MagicMock(return_value={
        "m1": [SimpleNamespace(id="a1", name="A1"), SimpleNamespace(id="a2", name="A2")],
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
            "t1",
            [{"activity_id": "a1", "percent_of_payment": Decimal("10")},
             {"activity_id": "a2", "percent_of_payment": Decimal("20")}],  # sums 30 != 45
            caller_user_id="u1",
        )


def test_term_activities_rejects_foreign_activity(monkeypatch):
    svc = _term_svc(monkeypatch)
    with pytest.raises(ValidationError):
        svc.set_payment_term_activities(
            "t1", [{"activity_id": "ZZZ", "percent_of_payment": Decimal("45")}],
            caller_user_id="u1",
        )


def test_term_activities_rejects_non_partial(monkeypatch):
    svc = _term_svc(monkeypatch, ptype="complete_payment")
    with pytest.raises(ValidationError):
        svc.set_payment_term_activities(
            "t1", [{"activity_id": "a1", "percent_of_payment": Decimal("45")}],
            caller_user_id="u1",
        )


def test_term_activities_persists_when_sum_matches(monkeypatch):
    svc = _term_svc(monkeypatch, term_pct="45")
    out = svc.set_payment_term_activities(
        "t1",
        [{"activity_id": "a1", "percent_of_payment": Decimal("20")},
         {"activity_id": "a2", "percent_of_payment": Decimal("25")}],  # sums 45
        caller_user_id="u1",
    )
    assert out == "TERM"
    svc.term_activities.replace_for_term.assert_called_once()
