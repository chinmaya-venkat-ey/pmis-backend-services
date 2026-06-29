"""Sandboxed arithmetic evaluator for master-driven carry-forward formulas.

Each ``masters.carry_forward_methods`` row carries a ``formula`` string that
computes the per-recipient carry-forward amount from a FIXED variable set:

    leftover          — the carrying phase's entire unallocated balance
    numRecipients     — count of recipients the leftover is split across
    recipientCycles   — payment cycles in THIS recipient's span (time-based)
    totalCycles       — Σ recipientCycles over all recipients (time-based)
    recipientPercent  — THIS recipient's custom share, 0..100 (custom)

The seeded built-ins:

    leftover / numRecipients              (evenly)
    leftover * recipientPercent / 100     (custom)
    leftover * recipientCycles / totalCycles   (time-based)

so a new variant is added as a master row, not as code.

Safety: the formula is parsed to an AST and evaluated by an explicit
whitelist walker — only numeric literals, the five names above, binary
``+ - * /``, parenthesised grouping and unary ``+/-`` are allowed. Names,
calls, attribute access, comprehensions, comparisons, etc. raise
``FormulaError``. Division by zero yields ``Decimal('0')`` (a recipient with
no cycles / a zero divisor simply receives nothing) rather than raising, so a
degenerate split can't 500 the payment page.

All arithmetic is ``Decimal`` to match the NUMERIC(18, 2) money columns.
"""
from __future__ import annotations

import ast
from decimal import Decimal
from typing import Mapping


ALLOWED_VARIABLES: tuple[str, ...] = (
    "leftover",
    "numRecipients",
    "recipientCycles",
    "totalCycles",
    "recipientPercent",
)

_ZERO = Decimal("0")


class FormulaError(ValueError):
    """Raised when a formula uses a disallowed construct or an unknown name."""


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _eval_node(node: ast.AST, variables: Mapping[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)

    # Numeric literal (py3.8+: ast.Constant).
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError(f"Disallowed literal: {node.value!r}")
        return _to_decimal(node.value)

    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise FormulaError(f"Unknown variable: {node.id!r}")
        return _to_decimal(variables[node.id])

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _eval_node(node.operand, variables)
        return operand if isinstance(node.op, ast.UAdd) else -operand

    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        # Division — guard a zero / missing divisor (degenerate split → 0).
        if right == _ZERO:
            return _ZERO
        return left / right

    raise FormulaError(f"Disallowed expression: {type(node).__name__}")


def evaluate(formula: str, variables: Mapping[str, Decimal]) -> Decimal:
    """Evaluate ``formula`` against ``variables`` and return a ``Decimal``.

    ``variables`` should supply every name the formula references (a subset of
    ``ALLOWED_VARIABLES``); a referenced name that is absent raises
    ``FormulaError``. The result is NOT rounded — callers quantize to 2dp and
    absorb the rounding remainder so a split conserves money exactly.
    """
    if not formula or not str(formula).strip():
        raise FormulaError("Empty formula")
    try:
        tree = ast.parse(str(formula).strip(), mode="eval")
    except SyntaxError as exc:  # pragma: no cover - defensive
        raise FormulaError(f"Unparseable formula: {exc}") from exc
    return _eval_node(tree, variables)
