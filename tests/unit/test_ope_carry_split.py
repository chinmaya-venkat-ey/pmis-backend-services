"""Independent partial OPE / other-cost carry-forward — bug #326.

Confirmed model: OPE stays in the billing base. A phase carries a configurable
% of its OPE forward phase-wise (the rest is retained and billed with the
phase); the other-cost stream carries its unbilled leftover at its own %.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace as NS

from app.utilities import payment_calc as pc


def _ci(**k):
    b = dict(cost_type_code=None, phase=None, cost=Decimal("0"), tax_amount=Decimal("0"),
             per_transaction_cost=None, planned_transactions=None, frequency_code=None,
             milestone_ids=[])
    b.update(k)
    return NS(**b)


def _term(phase, mid, pct):
    return NS(phase=phase, milestone_id=mid, cost_item_id=None,
              percent_of_payment=Decimal(pct))


_ROWS = [
    _ci(cost_type_code="fixed", phase="P1", cost=Decimal("100000"), milestone_ids=["m1"]),
    _ci(cost_type_code="fixed", phase="P2", cost=Decimal("100000"), milestone_ids=["m2"]),
    _ci(cost_type_code="one_time", cost=Decimal("40000")),
]
_TERMS = [_term("P1", "m1", "50"), _term("P2", "m2", "100")]
_CFG = {"P1": {"enabled": True, "method": "phase",
               "formula": "leftover / numRecipients", "recipient_vars": {}}}
_ALLOC = {"P1": Decimal("40000"), "P2": Decimal("0")}


def test_scenario_b_independent_split():
    split = {"P1": {"one_time_pct": Decimal("25"), "other_cost_pct": Decimal("35")}}
    cf = pc.carry_forward_distribution(_ROWS, _TERMS, ["P1", "P2"], _CFG,
                                       one_time_alloc=_ALLOC, carry_split_by_phase=split)
    # OPE: 25% of 40k = 10k carried, 30k retained (billed with P1)
    assert cf["one_time_carried_out"]["P1"] == Decimal("10000.00")
    assert cf["one_time_retained"]["P1"] == Decimal("30000.00")
    assert cf["one_time_received"]["P2"] == Decimal("10000.00")
    # combined base billed by the 50% term
    assert cf["effective_base"]["P1"] == Decimal("130000.00")
    assert cf["leftover"]["P1"] == Decimal("65000.00")
    # other-cost: 50k leftover, 35% carries = 17.5k
    assert cf["other_cost_leftover"]["P1"] == Decimal("50000.00")
    assert cf["carried_out"]["P1"] == Decimal("17500.00")
    assert cf["phase_received"]["P2"] == Decimal("17500.00")
    # P2 receives both streams: base = 100k fixed + 17.5k other-in + 10k OPE-in
    assert cf["effective_base"]["P2"] == Decimal("127500.00")


def test_ope_conservation():
    split = {"P1": {"one_time_pct": Decimal("25"), "other_cost_pct": Decimal("35")}}
    cf = pc.carry_forward_distribution(_ROWS, _TERMS, ["P1", "P2"], _CFG,
                                       one_time_alloc=_ALLOC, carry_split_by_phase=split)
    total_retained = cf["one_time_retained"]["P1"] + cf["one_time_retained"]["P2"]
    assert total_retained == Decimal("40000.00")  # whole pool ends up retained somewhere


def test_defaults_ope_stays_other_carries_full():
    # No split set → other-cost carries 100% (legacy), OPE stays (default 0).
    cf = pc.carry_forward_distribution(_ROWS, _TERMS, ["P1", "P2"], _CFG,
                                       one_time_alloc=_ALLOC)
    assert cf["one_time_carried_out"]["P1"] == Decimal("0.00")
    assert cf["effective_base"]["P1"] == Decimal("140000.00")   # full 40k OPE retained
    assert cf["carried_out"]["P1"] == Decimal("50000.00")       # 100% of other leftover
    assert cf["phase_received"]["P2"] == Decimal("50000.00")


def test_recurring_only_phase_never_receives_or_carries():
    rows = _ROWS + [_ci(cost_type_code="recurring_cost", phase="R",
                        cost=Decimal("50000"), frequency_code="yearly", milestone_ids=["mr"])]
    split = {"P1": {"one_time_pct": Decimal("50"), "other_cost_pct": Decimal("100")}}
    cf = pc.carry_forward_distribution(rows, _TERMS, ["P1", "P2", "R"], _CFG,
                                       one_time_alloc=_ALLOC, carry_split_by_phase=split)
    assert cf["one_time_received"].get("R", Decimal("0")) == Decimal("0")
    assert cf["phase_received"].get("R", Decimal("0")) == Decimal("0")
    assert cf["one_time_carried_out"].get("R", Decimal("0")) == Decimal("0")
