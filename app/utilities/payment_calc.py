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


# Carry-forward recipient UNITS (which master ``method`` distributes to what).
CF_PHASE = "phase"          # split across subsequent phases (grows their base)
CF_MILESTONE = "milestone"  # split across subsequent milestones (direct add-on)
CF_TIME = "time"            # split across subsequent phases, weighted by cycles

# Default formula for the legacy / evenly path (master ``*_evenly`` rows).
_EVENLY_FORMULA = "leftover / numRecipients"


def _normalize_cf_config(cfg: dict) -> dict:
    """Normalise a per-phase carry-forward config into ``{enabled, method,
    formula, recipient_vars}``.

    Accepts BOTH shapes:
      * new — ``{"enabled", "method", "variant", "formula", "recipient_vars"}``
        where ``method`` ∈ {phase, milestone, time}; ``recipient_vars`` maps a
        recipient key → extra formula variables (recipientCycles/totalCycles for
        time, recipientPercent for custom). Stage-3 evenly passes none.
      * legacy — ``{"enabled", "mode"}`` with ``mode`` ∈ {phase, milestone};
        treated as the matching ``*_evenly`` formula. Keeps the direct
        ``payment_calc`` unit tests + any un-migrated caller working.
    """
    if not cfg:
        return {"enabled": False, "method": None, "formula": _EVENLY_FORMULA, "recipient_vars": {}}
    method = cfg.get("method") or cfg.get("mode")
    formula = cfg.get("formula") or _EVENLY_FORMULA
    return {
        "enabled": bool(cfg.get("enabled")),
        "method": method,
        "formula": formula,
        "recipient_vars": cfg.get("recipient_vars") or {},
    }


def _distribute_by_formula(amount: Decimal, recipients, formula, acc: dict,
                           recipient_vars: Optional[dict] = None) -> Decimal:
    """Add ``amount`` distributed across ``recipients`` into accumulator ``acc``
    using ``formula`` (evaluated per recipient via the sandboxed engine).

    Each recipient r's raw share = ``round(evaluate(formula, {leftover,
    numRecipients, **recipient_vars[r]}))``. The rounding remainder
    (``amount − Σ raw``) is handed to the LAST recipient that has a positive
    share, so an explicit 0-share custom recipient never receives stray paise.
    When NO recipient has a positive share (e.g. a fully-stale custom config
    whose only allocated recipients dropped out of "subsequent"), nothing is
    distributed — the leftover stays with the carrying phase rather than being
    dumped onto an unallocated recipient. For the evenly formula (all shares
    equal) this is mathematically identical to the previous equal-split-with-
    last-absorbs behaviour. Returns the total distributed."""
    from app.utilities import formula_eval

    n = len(recipients)
    if n == 0 or amount <= _ZERO:
        return _ZERO
    per = recipient_vars or {}
    base_vars = {"leftover": amount, "numRecipients": Decimal(n)}
    raw = []
    for r in recipients:
        v = dict(base_vars)
        v.update(per.get(r, {}))
        raw.append(_round_money(formula_eval.evaluate(formula, v)))
    remainder = _round_money(amount - sum(raw, _ZERO))
    if remainder != _ZERO:
        idx = next((k for k in range(n - 1, -1, -1) if raw[k] > _ZERO), None)
        if idx is not None:  # absorb the rounding remainder into the last positive share
            raw[idx] = _round_money(raw[idx] + remainder)
        # else: no positive share anywhere → distribute nothing (carry stays put)
    distributed = _ZERO
    for r, s in zip(recipients, raw):
        if s > _ZERO:
            acc[r] = _round_money(acc.get(r, _ZERO) + s)
            distributed += s
    return _round_money(distributed)


def carry_forward_distribution(cost_rows, term_rows, ordered_phases, config_by_phase) -> dict:
    """Carry-forward ("carry forward cost") over phases in SEQUENCE order.

    A phase may opt in (``config_by_phase[phase]``) to carry its ENTIRE leftover
    (effective base − Σ %-payouts) forward. The master-driven ``method`` chooses
    the recipient UNIT and the ``formula`` chooses each recipient's SHARE:

      * ``"phase"`` / ``"time"`` — across all SUBSEQUENT phases' totals
                          (``phase_received`` grows their base; compounds down
                          the chain). ``time`` additionally weights shares by
                          per-phase cycle counts supplied in ``recipient_vars``.
      * ``"milestone"`` — across all SUBSEQUENT milestones' payable values
                          (``milestone_received``; a direct add-on, paid out, so
                          it does not re-enter a phase base).

    Config shape per phase (see ``_normalize_cf_config``): the new
    ``{"enabled", "method", "formula", "recipient_vars"}`` or the legacy
    ``{"enabled", "mode"}`` (evenly). A phase with no eligible recipients for
    its method carries nothing.

    Returns::

        {"phase_received": {phase: amt},       # phase-wise inflow (grows base)
         "milestone_received": {ms_id: amt},   # milestone-wise inflow (direct)
         "effective_base": {phase: amt},       # fixed(+one_time first) + phase_received
         "leftover": {phase: amt},             # effective_base − Σ %-payouts (≥0)
         "carried_out": {phase: amt}}          # leftover carried OUT (0 if none)
    """
    ordered = list(ordered_phases)
    phase_received = {p: _ZERO for p in ordered}
    milestone_received: dict = {}
    effective_base: dict = {}
    leftover: dict = {}
    carried_out = {p: _ZERO for p in ordered}
    one_time = one_time_total(cost_rows)

    # Milestone ids present per phase (from the live payment terms).
    ms_by_phase: dict = {}
    for t in term_rows:
        ph = getattr(t, "phase", None)
        mid = getattr(t, "milestone_id", None)
        if ph is not None and mid is not None:
            ms_by_phase.setdefault(ph, []).append(mid)

    for i, p in enumerate(ordered):
        base = phase_fixed_total(cost_rows, p)
        if i == 0:
            base += one_time
        base = _round_money(base + phase_received[p])
        effective_base[p] = base

        allocated = _ZERO
        for t in term_rows:
            if getattr(t, "phase", None) == p:
                allocated += payment_value(getattr(t, "percent_of_payment", None), base)
        lo = base - allocated
        lo = _round_money(lo) if lo > _ZERO else _ZERO
        leftover[p] = lo

        cfg = _normalize_cf_config(config_by_phase.get(p) or {})
        if cfg["enabled"] and lo > _ZERO:
            method = cfg["method"]
            formula = cfg["formula"]
            rvars = cfg["recipient_vars"]
            subsequent = ordered[i + 1:]
            if method in (CF_PHASE, CF_TIME) and subsequent:
                carried_out[p] = _distribute_by_formula(
                    lo, subsequent, formula, phase_received, rvars)
            elif method == CF_MILESTONE:
                sub_ms = [m for sp in subsequent for m in ms_by_phase.get(sp, [])]
                if sub_ms:
                    carried_out[p] = _distribute_by_formula(
                        lo, sub_ms, formula, milestone_received, rvars)

    return {
        "phase_received": phase_received,
        "milestone_received": milestone_received,
        "effective_base": effective_base,
        "leftover": leftover,
        "carried_out": carried_out,
    }
