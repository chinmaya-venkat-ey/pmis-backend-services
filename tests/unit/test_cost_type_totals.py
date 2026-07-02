"""Resource / transaction cost totals — flat planned expenses.

transaction line total = per_transaction_cost × planned_transactions;
resource line total = cost + tax; both add to a phase's expense total and to the
contract total, but never to the fixed (billable) base.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.utilities import payment_calc as pc


def _row(code, phase=None, cost=0, tax=0, per_txn=None, planned=None,
         billed_mode=None, billed_value=None):
    return SimpleNamespace(cost_type_code=code, phase=phase,
                           cost=Decimal(str(cost)), tax_amount=Decimal(str(tax)),
                           per_transaction_cost=(None if per_txn is None else Decimal(str(per_txn))),
                           planned_transactions=planned,
                           billed_mode=billed_mode,
                           billed_value=(None if billed_value is None else Decimal(str(billed_value))))


def test_transaction_total_is_product():
    assert pc.transaction_total(Decimal("1000"), 5) == Decimal("5000.00")
    assert pc.transaction_total(Decimal("1000"), 0) == Decimal("0")
    assert pc.transaction_total(None, 5) == Decimal("0")


def test_line_total_by_type():
    assert pc.line_total(_row("transaction_cost", per_txn=250, planned=4)) == Decimal("1000.00")
    assert pc.line_total(_row("resource_cost", cost=20000, tax=1000)) == Decimal("21000.00")
    assert pc.line_total(_row("fixed", cost=100000, tax=0)) == Decimal("100000.00")


def test_phase_expense_total_only_expenses_in_phase():
    rows = [
        _row("fixed", phase="A", cost=100000),
        _row("resource_cost", phase="A", cost=20000),
        _row("transaction_cost", phase="A", per_txn=1000, planned=5),   # 5000
        _row("resource_cost", phase="B", cost=9000),                    # other phase
    ]
    assert pc.phase_expense_total(rows, "A") == Decimal("25000.00")     # 20000 + 5000
    assert pc.phase_expense_total(rows, "B") == Decimal("9000.00")
    # fixed is NOT an expense
    assert pc.phase_fixed_total(rows, "A") == Decimal("100000.00")


def test_contract_totals_split_by_type():
    rows = [
        _row("fixed", phase="A", cost=100000),
        _row("one_time", cost=50000),
        _row("resource_cost", phase="A", cost=20000),
        _row("transaction_cost", phase="A", per_txn=1000, planned=5),   # 5000
    ]
    t = pc.contract_totals(rows)
    assert t["fixed_cost"] == Decimal("100000.00")
    assert t["one_time_cost"] == Decimal("50000.00")
    assert t["resource_cost"] == Decimal("20000.00")
    assert t["transaction_cost"] == Decimal("5000.00")
    assert t["total_contract_cost"] == Decimal("175000.00")            # 100000+50000+20000+5000


# ---------------------- billed split (resource/transaction in carry-forward) --

def test_line_billed_defaults_to_full_value():
    assert pc.line_billed(_row("resource_cost", cost=20000)) == Decimal("20000.00")   # no billed spec
    assert pc.line_unbilled(_row("resource_cost", cost=20000)) == Decimal("0.00")


def test_line_billed_percent_and_amount():
    r = _row("resource_cost", cost=20000, billed_mode="percent", billed_value=60)
    assert pc.line_billed(r) == Decimal("12000.00")
    assert pc.line_unbilled(r) == Decimal("8000.00")
    a = _row("resource_cost", cost=20000, billed_mode="amount", billed_value=15000)
    assert pc.line_billed(a) == Decimal("15000.00")
    assert pc.line_unbilled(a) == Decimal("5000.00")
    # amount over the value is capped
    over = _row("resource_cost", cost=20000, billed_mode="amount", billed_value=99999)
    assert pc.line_billed(over) == Decimal("20000.00")
    assert pc.line_unbilled(over) == Decimal("0.00")


def test_phase_expense_billed_and_unbilled():
    rows = [
        _row("fixed", phase="A", cost=100000),
        _row("resource_cost", phase="A", cost=20000, billed_mode="percent", billed_value=60),   # 12000/8000
        _row("transaction_cost", phase="A", per_txn=1000, planned=5),                            # 5000/0 (default)
    ]
    assert pc.phase_expense_billed(rows, "A") == Decimal("17000.00")     # 12000 + 5000
    assert pc.phase_expense_unbilled(rows, "A") == Decimal("8000.00")    # 8000 + 0


def _term(phase, pct, mid):
    return SimpleNamespace(phase=phase, percent_of_payment=Decimal(str(pct)), milestone_id=mid)


def test_carry_forward_leftover_includes_unbilled_expense():
    # phase 1: fixed 10000, term 0% (whole fixed is leftover) + a resource 20000 at 60% (8000 unbilled).
    cost_rows = [_row("fixed", phase="1", cost=10000), _row("fixed", phase="2", cost=5000),
                 _row("resource_cost", phase="1", cost=20000, billed_mode="percent", billed_value=60)]
    term_rows = [_term("1", 0, "m1"), _term("2", 0, "m2")]
    cf = pc.carry_forward_distribution(cost_rows, term_rows, ["1", "2"], {})
    assert cf["leftover"]["1"] == Decimal("18000.00")   # 10000 fixed leftover + 8000 unbilled expense
