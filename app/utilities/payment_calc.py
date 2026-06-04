"""Pure-function calculators for the Project-Finance payment screen.

All amounts are INR rupees as ``Decimal`` (matches the NUMERIC(18, 2)
columns). No DB access, no side effects — this module is the single source
of truth for every derived figure on the payment page, used by the cost-item
/ payment-term / phase services and the aggregated payment-page builder.

Calculation rules (everything is "on change" — recompute from the rows):

* ``row_total``          — per cost row, ``cost + tax_amount`` (tax is now an
                           exact AMOUNT the user enters, not a percentage; the
                           legacy ``tax_percent`` column is kept but unused).
* ``total_contract_cost``— Σ ``row_total`` across every live cost row.
* ``fixed_cost``         — Σ ``row_total`` of rows with cost_type 'fixed'.
* ``one_time_cost``      — Σ ``row_total`` of rows with cost_type 'one_time'.
* ``phase_fixed_total``  — Σ ``row_total`` of the FIXED cost rows in a phase.
                           This is the base a phase's payment terms split.
* ``payment_value``      — per payment-term row,
                           ``percent_of_payment/100 × phase_fixed_total``
                           (PHASE-based: the % is a share of the whole phase).
* ``qrg_value``          — per phase (when QRG applied),
                           ``phase_fixed_total − Σ payment_value`` (the
                           unallocated balance carried forward). Never below 0.
* ``qrg_percent``        — ``100 − Σ percent_of_payment`` in the phase.
* ``ccn_value``          — ``total_contract_cost × ccn_cap_percent/100``.

``None`` inputs coerce to 0 (every value field is nullable for now).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_QUANTIZE = Decimal("0.01")

FIXED = "fixed"
ONE_TIME = "one_time"


def _to_decimal(value) -> Decimal:
    """Coerce ``None``/int/float/str/Decimal → Decimal. NULL → 0."""
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(_QUANTIZE, rounding=ROUND_HALF_UP)


def row_total(cost, tax_amount) -> Decimal:
    """Inclusive-tax total for a single cost row: ``cost + tax_amount``.
    Tax is an exact amount (e.g. 1000 on a 10000 cost → total 11000). Both
    inputs coerce NULL → 0."""
    return _round_money(_to_decimal(cost) + _to_decimal(tax_amount))


def payment_value(percent_of_payment, phase_fixed_total) -> Decimal:
    """A payment-term row's value: ``percent/100 × phase fixed total``."""
    pct = _to_decimal(percent_of_payment)
    base = _to_decimal(phase_fixed_total)
    if pct <= _ZERO or base <= _ZERO:
        return _ZERO
    return _round_money(base * pct / _HUNDRED)


def qrg_value(phase_fixed_total, allocated_value_sum) -> Decimal:
    """Unallocated balance for a phase (carry-forward): ``phase fixed total
    − Σ allocated payment values``. Clamped at 0 (never negative)."""
    remainder = _to_decimal(phase_fixed_total) - _to_decimal(allocated_value_sum)
    if remainder <= _ZERO:
        return _ZERO
    return _round_money(remainder)


def qrg_percent(allocated_percent_sum) -> Decimal:
    """Auto-derived QRG percent: ``100 − Σ percent_of_payment``. Clamped 0."""
    remainder = _HUNDRED - _to_decimal(allocated_percent_sum)
    if remainder <= _ZERO:
        return _ZERO
    return _round_money(remainder)


def ccn_value(total_contract_cost, ccn_cap_percent) -> Decimal:
    """CCN value = ``total contract cost × ccn_cap_percent / 100``."""
    base = _to_decimal(total_contract_cost)
    pct = _to_decimal(ccn_cap_percent)
    if base <= _ZERO or pct <= _ZERO:
        return _ZERO
    return _round_money(base * pct / _HUNDRED)


def to_2dp(value) -> Decimal:
    """Public helper: coerce any value to a 2dp Decimal (NULL → 0.00)."""
    return _round_money(_to_decimal(value))


# --------------------------------------------------------------------------
# Aggregation over cost-item rows. ``items`` is any iterable of objects with
# ``cost_type_code`` / ``phase`` / ``cost`` / ``tax_amount`` attributes
# (ORM rows work directly). No DB access — the caller loads the rows.
# --------------------------------------------------------------------------

def _code(item) -> str:
    return str(getattr(item, "cost_type_code", None) or "").lower()


def contract_totals(items) -> dict:
    """Return ``{total_contract_cost, fixed_cost, one_time_cost}`` (2dp)."""
    total = _ZERO
    fixed = _ZERO
    one_time = _ZERO
    for it in items:
        rt = row_total(getattr(it, "cost", None), getattr(it, "tax_amount", None))
        total += rt
        code = _code(it)
        if code == FIXED:
            fixed += rt
        elif code == ONE_TIME:
            one_time += rt
    return {
        "total_contract_cost": _round_money(total),
        "fixed_cost": _round_money(fixed),
        "one_time_cost": _round_money(one_time),
    }


def phase_fixed_total(items, phase) -> Decimal:
    """Σ ``row_total`` of FIXED cost rows in ``phase`` — the base a phase's
    payment terms split. Returns a 2dp Decimal."""
    total = _ZERO
    for it in items:
        if _code(it) == FIXED and getattr(it, "phase", None) == phase:
            total += row_total(getattr(it, "cost", None), getattr(it, "tax_amount", None))
    return _round_money(total)


def qrg_caps(cost_rows, term_rows, qrg_phase) -> dict:
    """QRG distribution (Option A — amount-based, money-conserving).

    At most ONE phase carries QRG (``qrg_phase``; ``None`` = no QRG). Its
    unallocated leftover (``phaseTotal − Σ payouts``) is split EQUALLY by
    amount across the SUBSEQUENT phases (number > qrg_phase) that have cost
    rows. Each such phase's 100% budget rises by its share, expressed as a
    higher cap: ``effective_cap = 100 + share/phaseTotal × 100``. Milestone
    ``value`` stays ``% × that phase's own total``; the higher cap just lets
    the phase absorb its QRG share.

    Returns ``{"caps": {phase: cap%}, "received": {phase: amount},
    "leftover": amount, "distributed": amount}``. Caps default to 100, received
    to 0. Pure — the caller loads the rows.
    """
    phases = sorted({
        getattr(c, "phase", None) for c in cost_rows
        if _code(c) == FIXED and getattr(c, "phase", None) is not None
    })
    caps = {p: _HUNDRED for p in phases}
    received = {p: _ZERO for p in phases}
    leftover = _ZERO
    distributed = _ZERO

    if qrg_phase is not None:
        qpt = phase_fixed_total(cost_rows, qrg_phase)
        allocated = _ZERO
        for t in term_rows:
            if getattr(t, "phase", None) == qrg_phase:
                allocated += payment_value(getattr(t, "percent_of_payment", None), qpt)
        leftover = qrg_value(qpt, allocated)
        later = [p for p in phases if p > qrg_phase and phase_fixed_total(cost_rows, p) > _ZERO]
        if later and leftover > _ZERO:
            share = leftover / Decimal(len(later))
            for p in later:
                pt = phase_fixed_total(cost_rows, p)
                received[p] = _round_money(share)
                caps[p] = _round_money(_HUNDRED + share / pt * _HUNDRED)
            distributed = _round_money(leftover)

    return {
        "caps": caps,
        "received": received,
        "leftover": _round_money(leftover),
        "distributed": distributed,
    }
