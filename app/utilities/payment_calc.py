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
    """Σ ``row_total`` of FIXED cost rows in ``phase`` — the FIXED-only total of
    a phase. Returns a 2dp Decimal."""
    total = _ZERO
    for it in items:
        if _code(it) == FIXED and getattr(it, "phase", None) == phase:
            total += row_total(getattr(it, "cost", None), getattr(it, "tax_amount", None))
    return _round_money(total)


def one_time_total(items) -> Decimal:
    """Σ ``row_total`` of the ONE-TIME cost rows. Folded into the first phase's
    payment base (see ``phase_payment_base``)."""
    total = _ZERO
    for it in items:
        if _code(it) == ONE_TIME:
            total += row_total(getattr(it, "cost", None), getattr(it, "tax_amount", None))
    return _round_money(total)


def first_phase(items):
    """The lowest phase number present on the cost rows (dynamic — not
    hard-coded to 1). ``None`` when no phased cost rows exist."""
    phases = [
        getattr(c, "phase", None) for c in items
        if _code(c) == FIXED and getattr(c, "phase", None) is not None
    ]
    return min(phases) if phases else None


def phase_payment_base(items, phase) -> Decimal:
    """The base a phase's payment terms split — its FIXED total, PLUS the whole
    One-Time amount when ``phase`` is the FIRST (lowest) phase. The One-Time row
    has no phase of its own; its amount is folded into the first phase so the
    milestone %s there are valued on ``fixed + one_time`` together."""
    base = phase_fixed_total(items, phase)
    if phase == first_phase(items):
        base += one_time_total(items)
    return _round_money(base)


def qrg_distribution(cost_rows, term_rows, qrg_phase) -> dict:
    """QRG distribution (Option A — amount-based, money-conserving).

    At most ONE phase carries QRG (``qrg_phase``; ``None`` = no QRG). Its
    unallocated leftover (``phaseTotal − Σ payouts``) is split EQUALLY by
    amount across the SUBSEQUENT phases (number > qrg_phase) that have cost
    rows. Each such phase's **total grows** by its share, so its EFFECTIVE
    TOTAL = ``phaseTotal + qrgReceived`` (e.g. 15000 + 2000 = 17000). Milestone
    %s are still capped at 100% but valued on this larger total.

    Returns ``{"received": {phase: amount}, "leftover": amount,
    "distributed": amount}``. ``received`` defaults to 0. Pure — the caller
    loads the rows and computes ``effective_total = phaseTotal + received``.
    """
    phases = sorted({
        getattr(c, "phase", None) for c in cost_rows
        if _code(c) == FIXED and getattr(c, "phase", None) is not None
    })
    received = {p: _ZERO for p in phases}
    leftover = _ZERO
    distributed = _ZERO

    if qrg_phase is not None:
        qpt = phase_payment_base(cost_rows, qrg_phase)
        allocated = _ZERO
        for t in term_rows:
            if getattr(t, "phase", None) == qrg_phase:
                allocated += payment_value(getattr(t, "percent_of_payment", None), qpt)
        leftover = qrg_value(qpt, allocated)
        later = [p for p in phases if p > qrg_phase and phase_payment_base(cost_rows, p) > _ZERO]
        if later and leftover > _ZERO:
            share = leftover / Decimal(len(later))
            for p in later:
                received[p] = _round_money(share)
            distributed = _round_money(leftover)

    return {
        "received": received,
        "leftover": _round_money(leftover),
        "distributed": distributed,
    }


# Carry-forward modes (per-phase config — replaces the auto QRG split).
CF_PERCENT = "percent"
CF_AMOUNT = "amount"


def phase_base_with_one_time(items, phase, *, is_first: bool) -> Decimal:
    """Phase FIXED total, plus the whole One-Time amount when this is the FIRST
    phase by SEQUENCE (``is_first``). Unlike the legacy ``phase_payment_base``
    this takes ``is_first`` explicitly so ordering follows the phase sequence,
    not the lexical phase name."""
    base = phase_fixed_total(items, phase)
    if is_first:
        base += one_time_total(items)
    return _round_money(base)


def carry_forward_distribution(cost_rows, term_rows, ordered_phases, config_by_phase) -> dict:
    """Carry-forward ("carry forward cost", ex-QRG) over phases in SEQUENCE order.

    Each phase may opt in (``config_by_phase[phase] = {"enabled", "mode",
    "percent", "amount"}``) to carry its *leftover* (the unallocated balance
    after its milestone payouts) to the IMMEDIATELY-NEXT phase. It COMPOUNDS:
    a phase's base includes what it received, so its own leftover (and onward
    carry) can include amounts handed down the chain. The last phase can never
    carry forward (no successor).

    ``ordered_phases`` is the list of phase names in ascending sequence order.
    Returns per-phase maps::

        {"received": {p: amount},        # carried INTO p from p-1
         "effective_base": {p: amount},  # fixed(+one_time on first) + received
         "leftover": {p: amount},        # effective_base − Σ payouts (≥0)
         "carried_out": {p: amount}}     # carried OUT of p to p+1
    """
    ordered = list(ordered_phases)
    received = {p: _ZERO for p in ordered}
    effective_base: dict = {}
    leftover: dict = {}
    carried_out = {p: _ZERO for p in ordered}
    one_time = one_time_total(cost_rows)
    n = len(ordered)

    for i, p in enumerate(ordered):
        base = phase_fixed_total(cost_rows, p)
        if i == 0:
            base += one_time
        base = _round_money(base + received[p])
        effective_base[p] = base

        allocated = _ZERO
        for t in term_rows:
            if getattr(t, "phase", None) == p:
                allocated += payment_value(getattr(t, "percent_of_payment", None), base)
        lo = base - allocated
        lo = _round_money(lo) if lo > _ZERO else _ZERO
        leftover[p] = lo

        cfg = config_by_phase.get(p) or {}
        is_last = i == n - 1
        carried = _ZERO
        if cfg.get("enabled") and not is_last and lo > _ZERO:
            mode = cfg.get("mode")
            if mode == CF_AMOUNT:
                carried = min(_to_decimal(cfg.get("amount")), lo)
            elif mode == CF_PERCENT:
                carried = min(_round_money(lo * _to_decimal(cfg.get("percent")) / _HUNDRED), lo)
        carried = _round_money(carried) if carried > _ZERO else _ZERO
        if carried > _ZERO:
            nxt = ordered[i + 1]
            received[nxt] = _round_money(received[nxt] + carried)
            carried_out[p] = carried

    return {
        "received": received,
        "effective_base": effective_base,
        "leftover": leftover,
        "carried_out": carried_out,
    }
