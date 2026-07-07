"""Server-side finance validation checks (pure function, no DB)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace as N

from app.utilities.finance_validation import run_finance_validation


def _term(pct, mid="m1", acts=None, sd=None, ed=None, cycle=None):
    return N(percent_of_payment=(None if pct is None else Decimal(str(pct))),
             milestone_id=mid, activities=acts or [], start_date=sd, end_date=ed, cycle_count=cycle)


def _cost(code="fixed", total=1000, phase="1", ms=("m1",), tax=0, per=None, planned=None):
    return N(cost_type_code=code, total=Decimal(str(total)), phase=phase,
             milestone_ids=list(ms), tax_amount=Decimal(str(tax)),
             per_transaction_cost=(None if per is None else Decimal(str(per))),
             planned_transactions=planned)


def _phase(name="1", terms=None, cf=False, one_time=0):
    return N(phase=name, payment_terms=terms or [], carry_forward=N(enabled=cf),
             one_time_allocated=Decimal(str(one_time)))


def _page(*, cost_items, phases, total=1000, one_time=0, cap=25, freq="quarterly"):
    return N(totals=N(total_contract_cost=Decimal(str(total)), one_time_cost=Decimal(str(one_time))),
             cost_items=cost_items, phases=phases, ccn=N(cap_percent=Decimal(str(cap))),
             frequency_code=freq)


def _by_id(res):
    return {c["id"]: c for c in res["checks"]}


def test_clean_finance_all_pass():
    page = _page(
        cost_items=[_cost(total=1000, ms=("m1",))],
        phases=[_phase("1", terms=[_term(100, "m1")])],  # single phase = last -> 100%
        total=1000, cap=25)
    res = run_finance_validation(page, active_milestone_ids={"m1"})
    assert res["all_pass"] is True, [c for c in res["checks"] if not c["pass"]]


def test_empty_finance_fails_the_right_checks():
    page = _page(cost_items=[], phases=[], total=0, cap=150)
    r = _by_id(run_finance_validation(page, active_milestone_ids={"m1"}))
    assert r["total-cost"]["pass"] is False
    assert r["has-cost-item"]["pass"] is False
    assert r["ccn-cap"]["pass"] is False          # 150 out of range
    assert r["milestone-linked"]["pass"] is False  # m1 orphaned
    assert run_finance_validation(page, {"m1"})["all_pass"] is False


def test_last_phase_not_100_and_orphan_row():
    page = _page(
        cost_items=[_cost(total=1000, ms=())],                 # no milestone
        phases=[_phase("1", terms=[_term(90, "m1")])],         # last phase only 90%
        total=1000)
    r = _by_id(run_finance_validation(page, active_milestone_ids=set()))
    assert r["row-milestone"]["pass"] is False
    assert r["term-pct"]["pass"] is False and "100%" in r["term-pct"]["reason"]


def test_transaction_missing_fields_and_bad_dates():
    page = _page(
        cost_items=[_cost(code="transaction_cost", total=0, per=None, planned=None, ms=("m1",))],
        phases=[_phase("1", terms=[_term(100, "m1", sd=datetime(2027, 6, 1), ed=datetime(2027, 1, 1))])],
        total=1)
    r = _by_id(run_finance_validation(page, active_milestone_ids={"m1"}))
    assert r["txn-fields"]["pass"] is False
    assert r["cost-row-value"]["pass"] is False       # total 0
    assert r["milestone-dates"]["pass"] is False      # start > end
