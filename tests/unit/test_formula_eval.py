"""Sandboxed carry-forward formula evaluator."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.utilities.formula_eval import FormulaError, evaluate


def test_evenly_formula():
    out = evaluate("leftover / numRecipients",
                   {"leftover": Decimal("5500"), "numRecipients": Decimal("2")})
    assert out == Decimal("2750")


def test_custom_percent_formula():
    out = evaluate("leftover * recipientPercent / 100",
                   {"leftover": Decimal("1000"), "recipientPercent": Decimal("30")})
    assert out == Decimal("300")


def test_time_weighted_formula():
    out = evaluate("leftover * recipientCycles / totalCycles",
                   {"leftover": Decimal("900"), "recipientCycles": Decimal("2"),
                    "totalCycles": Decimal("3")})
    assert out == Decimal("600")


def test_parentheses_and_unary():
    assert evaluate("-(leftover - 100)", {"leftover": Decimal("30")}) == Decimal("70")


def test_division_by_zero_yields_zero():
    # A degenerate split (no recipients / no cycles) pays nothing, never raises.
    assert evaluate("leftover / numRecipients",
                    {"leftover": Decimal("10"), "numRecipients": Decimal("0")}) == Decimal("0")
    assert evaluate("leftover * recipientCycles / totalCycles",
                    {"leftover": Decimal("10"), "recipientCycles": Decimal("0"),
                     "totalCycles": Decimal("0")}) == Decimal("0")


def test_unknown_variable_raises():
    with pytest.raises(FormulaError):
        evaluate("leftover * bogus", {"leftover": Decimal("10")})


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hi')",
    "leftover.real",
    "abs(leftover)",
    "leftover ** 2",
    "[leftover for _ in range(3)]",
    "leftover if leftover else 0",
])
def test_disallowed_constructs_raise(expr):
    with pytest.raises(FormulaError):
        evaluate(expr, {"leftover": Decimal("10")})


def test_empty_formula_raises():
    with pytest.raises(FormulaError):
        evaluate("   ", {"leftover": Decimal("10")})
