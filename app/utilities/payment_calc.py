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
RESOURCE_COST = "resource_cost"
TRANSACTION_COST = "transaction_cost"
# A recurring cost is a project-level amount (like one_time — no phase, no
# milestones) that is distributed across frequency periods as a payment SCHEDULE
# from the milestone-timeline start over the project duration. It contributes
# its full line total to the contract cost but does NOT bill via milestone
# payment terms (its schedule is computed on the payment page).
RECURRING_COST = "recurring_cost"

# Resource / transaction cost lines are now FIRST-CLASS phase cost lines, just
# like fixed: they carry milestones, contribute their value to the phase base,
# and are paid out via milestone payment-term %s (transaction value =
# per_transaction_cost × planned_transactions). ``one_time`` remains the only
# non-phase, non-milestone cost type (a separate project pool).
EXPENSE_TYPES = (RESOURCE_COST, TRANSACTION_COST)
# Every cost type that lives on a phase and bills via milestone payment terms.
PHASE_COST_TYPES = (FIXED, RESOURCE_COST, TRANSACTION_COST)


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


def is_recurring(item) -> bool:
    """True when a cost row is a ``recurring_cost`` line — billed via its own
    dated frequency schedule, NOT via milestone payment-term %s."""
    return _code(item) == RECURRING_COST


def transaction_total(per_transaction_cost, planned_transactions) -> Decimal:
    """A transaction-cost line's total: ``per_transaction_cost × planned_transactions``.
    Either input NULL/≤0 → 0."""
    per = _to_decimal(per_transaction_cost)
    n = _to_decimal(planned_transactions)
    if per <= _ZERO or n <= _ZERO:
        return _ZERO
    return _round_money(per * n)


def line_total(item) -> Decimal:
    """The money a cost row contributes: transaction-cost rows use
    ``per_transaction_cost × planned_transactions + tax_amount``; every other
    type uses ``cost + tax_amount``. Tax is added for every type, so a
    transaction line's total is inclusive of tax exactly like a fixed line."""
    if _code(item) == TRANSACTION_COST:
        sub = transaction_total(
            getattr(item, "per_transaction_cost", None),
            getattr(item, "planned_transactions", None),
        )
        return _round_money(sub + _to_decimal(getattr(item, "tax_amount", None)))
    return row_total(getattr(item, "cost", None), getattr(item, "tax_amount", None))


def contract_totals(items) -> dict:
    """Return ``{total_contract_cost, fixed_cost, one_time_cost, resource_cost,
    transaction_cost, recurring_cost}`` (2dp). ``total_contract_cost`` is every
    row's line total."""
    total = _ZERO
    fixed = _ZERO
    one_time = _ZERO
    resource = _ZERO
    transaction = _ZERO
    recurring = _ZERO
    for it in items:
        lt = line_total(it)
        total += lt
        code = _code(it)
        if code == FIXED:
            fixed += lt
        elif code == ONE_TIME:
            one_time += lt
        elif code == RESOURCE_COST:
            resource += lt
        elif code == TRANSACTION_COST:
            transaction += lt
        elif code == RECURRING_COST:
            recurring += lt
    return {
        "total_contract_cost": _round_money(total),
        "fixed_cost": _round_money(fixed),
        "one_time_cost": _round_money(one_time),
        "resource_cost": _round_money(resource),
        "transaction_cost": _round_money(transaction),
        "recurring_cost": _round_money(recurring),
    }


def phase_expense_total(items, phase) -> Decimal:
    """Σ line total (full value) of the RESOURCE / TRANSACTION rows in ``phase``."""
    total = _ZERO
    for it in items:
        if _code(it) in EXPENSE_TYPES and getattr(it, "phase", None) == phase:
            total += line_total(it)
    return _round_money(total)


def phase_fixed_total(items, phase) -> Decimal:
    """Σ ``row_total`` of FIXED cost rows in ``phase`` — the FIXED-only subtotal
    (informational; the full billable base is ``phase_base_total``). 2dp."""
    total = _ZERO
    for it in items:
        if _code(it) == FIXED and getattr(it, "phase", None) == phase:
            total += row_total(getattr(it, "cost", None), getattr(it, "tax_amount", None))
    return _round_money(total)


def phase_base_total(items, phase) -> Decimal:
    """Σ ``line_total`` of every PHASE cost line (fixed + resource + transaction)
    in ``phase`` — the base a phase's milestone payment terms split. Resource and
    transaction lines contribute their value here exactly like fixed; a
    transaction line's value is ``per_transaction_cost × planned_transactions``."""
    total = _ZERO
    for it in items:
        if _code(it) in PHASE_COST_TYPES and getattr(it, "phase", None) == phase:
            total += line_total(it)
    return _round_money(total)


def phase_recurring_total(items, phase) -> Decimal:
    """Σ ``line_total`` of the RECURRING cost rows in ``phase`` — the combined
    recurring amount that phase spreads across its date span as a schedule
    (recurring rows do not bill via percentage terms, so this is NOT part of
    ``phase_base_total``). 2dp."""
    total = _ZERO
    for it in items:
        if _code(it) == RECURRING_COST and getattr(it, "phase", None) == phase:
            total += line_total(it)
    return _round_money(total)


def recurring_only_phases(items) -> set:
    """Phases whose cost is ENTIRELY recurring.

    A recurring row bills via its own dated frequency schedule, not via
    milestone payment-term %s. A phase carrying ONLY recurring rows therefore
    sits OUTSIDE the normal phase sequence — it exists to display its date span
    and that schedule. Such a phase:

      * takes no payment-term % (and must not be failed for a blank %),
      * takes no ONE-TIME (out-of-pocket) share — including the last-phase
        remainder, which would otherwise dump the whole pool on it,
      * neither carries leftover forward NOR receives carry-forward.

    A MIXED phase (recurring + fixed/resource/transaction) is deliberately NOT
    included — its billing lines still need the normal treatment.
    """
    recurring: set = set()
    billing: set = set()
    for it in items:
        phase = getattr(it, "phase", None)
        if phase is None:
            continue
        code = _code(it)
        if code == RECURRING_COST:
            recurring.add(phase)
        elif code in PHASE_COST_TYPES:
            billing.add(phase)
    return recurring - billing


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
        return {"enabled": False, "method": None, "formula": _EVENLY_FORMULA,
                "recipient_vars": {}, "frequency": None}
    method = cfg.get("method") or cfg.get("mode")
    formula = cfg.get("formula") or _EVENLY_FORMULA
    return {
        "enabled": bool(cfg.get("enabled")),
        "method": method,
        "formula": formula,
        "recipient_vars": cfg.get("recipient_vars") or {},
        # Frequency (monthly/quarterly/…) for the POOL family (time methods).
        "frequency": cfg.get("frequency"),
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
    # Only absorb a ROUNDING-scale remainder (≤ 1 paise per recipient) into the
    # last positive share. A larger gap means the shares intentionally sum to
    # < 100% — e.g. a stale custom allocation whose recipient dropped out of
    # "subsequent" — so that un-allocated portion is left with the carrying
    # phase rather than silently dumped onto the last recipient.
    rounding_tol = Decimal(n) * Decimal("0.01")
    if remainder != _ZERO and abs(remainder) <= rounding_tol:
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


def _phase_one_time_share(cfg, pool) -> Decimal:
    """A phase's explicit one-time share: ``value`` as a percent of the pool, or
    a ₹ amount. NULL/≤0 → 0."""
    v = _to_decimal(cfg.get("value"))
    if v <= _ZERO:
        return _ZERO
    if (cfg.get("mode") or "").lower() == "percent":
        return _round_money(pool * v / _HUNDRED)
    return _round_money(v)


def one_time_distribution(cost_rows, ordered_phases, one_time_config) -> dict:
    """Distribute the project ONE-TIME pool across phases.

    ``one_time_config[phase] = {"enabled", "mode", "value"}``. Each NON-last
    opted-in phase takes its explicit share (percent of the pool, or a ₹ amount),
    clamped so the running total never exceeds the pool. The chronologically LAST
    phase auto-absorbs the remainder, so the pool is always fully used. Returns
    ``{phase: allocated_amount}`` (0 for phases that take no share)."""
    ordered = list(ordered_phases)
    alloc = {p: _ZERO for p in ordered}
    pool = one_time_total(cost_rows)
    if not ordered or pool <= _ZERO:
        return alloc
    # Recurring-only phases are outside the billing sequence and take NO
    # one-time (out-of-pocket) share. They are dropped from the eligible list
    # entirely — otherwise a trailing recurring phase would absorb the whole
    # remainder as the "last phase".
    excluded = recurring_only_phases(cost_rows)
    eligible = [p for p in ordered if p not in excluded]
    if not eligible:
        return alloc
    used = _ZERO
    for p in eligible[:-1]:
        cfg = one_time_config.get(p) or {}
        if cfg.get("enabled"):
            share = _phase_one_time_share(cfg, pool)
            if share > pool - used:      # defensive clamp (write path validates the cap)
                share = _round_money(pool - used)
            if share < _ZERO:
                share = _ZERO
            alloc[p] = share
            used = _round_money(used + share)
    alloc[eligible[-1]] = _round_money(pool - used)  # last ELIGIBLE phase = the remainder
    return alloc


def one_time_allocation_summary(cost_rows, ordered_phases, one_time_config) -> dict:
    """OPE (one-time) allocation guide for the payment page — a pre-validate /
    publish aid, NOT a billing figure.

    ``allocated`` is how much of the one-time pool the user has EXPLICITLY
    assigned to phases (each opted-in non-terminal phase's share, clamped so the
    running total never exceeds the pool — the same explicit shares
    :func:`one_time_distribution` lays down, MINUS the remainder it auto-absorbs
    onto the last phase). ``pending`` = ``pool − allocated`` is the amount still
    unallocated; publishing requires it to be 0 (the pool must be fully
    allocated). Keep the explicit-share loop below in sync with
    :func:`one_time_distribution`.

    Returns ``{"pool", "allocated", "pending"}`` (all ₹, 2dp).
    """
    pool = one_time_total(cost_rows)
    ordered = list(ordered_phases)
    excluded = recurring_only_phases(cost_rows)
    eligible = [p for p in ordered if p not in excluded]
    if pool <= _ZERO or not eligible:
        return {"pool": _round_money(pool), "allocated": _ZERO,
                "pending": _round_money(pool)}
    used = _ZERO
    for p in eligible[:-1]:                       # last eligible phase auto-absorbs → pending
        cfg = one_time_config.get(p) or {}
        if cfg.get("enabled"):
            share = _phase_one_time_share(cfg, pool)
            if share > pool - used:               # same defensive clamp as one_time_distribution
                share = _round_money(pool - used)
            if share < _ZERO:
                share = _ZERO
            used = _round_money(used + share)
    allocated = _round_money(used)
    return {"pool": _round_money(pool), "allocated": allocated,
            "pending": _round_money(pool - allocated)}


def carry_forward_distribution(cost_rows, term_rows, ordered_phases, config_by_phase,
                               one_time_alloc=None, phase_dates=None,
                               project_bounds=None) -> dict:
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

    One-time (OPE) allocation joins each phase's billable base and carries
    forward CLUBBED with the other costs as one leftover. Recurring-only phases
    are outside the billing sequence — they never carry, and are never recipients.

    Returns::

        {"phase_received": {phase: amt},       # phase-wise inflow (grows base)
         "milestone_received": {ms_id: amt},   # milestone-wise inflow (direct)
         "effective_base": {phase: amt},       # fixed(+one_time) + phase_received
         "leftover": {phase: amt},             # effective_base − Σ %-payouts (≥0)
         "carried_out": {phase: amt}}          # leftover carried OUT (0 if none)
    """
    ordered = list(ordered_phases)
    phase_received = {p: _ZERO for p in ordered}
    milestone_received: dict = {}
    effective_base: dict = {}
    leftover: dict = {}
    carried_out = {p: _ZERO for p in ordered}
    pool: dict = {}  # source_phase -> [dated installment dicts] (frequency methods)
    # One-time is distributed to phases (see one_time_distribution) and joins
    # each phase's billable base — it is NO LONGER auto-folded into the first phase.
    one_time_alloc = one_time_alloc or {}
    phase_dates = phase_dates or {}
    # Recurring-only phases sit outside the billing sequence: they never carry
    # their (display-only) balance forward, and they are never a recipient of
    # another phase's carry-forward.
    excluded_phases = recurring_only_phases(cost_rows)

    # Milestone ids present per phase (from the live payment terms).
    ms_by_phase: dict = {}
    for t in term_rows:
        ph = getattr(t, "phase", None)
        mid = getattr(t, "milestone_id", None)
        if ph is not None and mid is not None:
            ms_by_phase.setdefault(ph, []).append(mid)

    for i, p in enumerate(ordered):
        base = phase_base_total(cost_rows, p) + one_time_alloc.get(p, _ZERO)
        base = _round_money(base + phase_received[p])
        effective_base[p] = base

        allocated = _ZERO
        for t in term_rows:
            if getattr(t, "phase", None) == p:
                allocated += payment_value(getattr(t, "percent_of_payment", None), base)
        # Leftover = the phase base not yet allocated by its milestone %s. Fixed,
        # resource and transaction lines all bill via those %s, so their
        # unallocated remainder simply carries forward together.
        lo = base - allocated
        lo = _round_money(lo) if lo > _ZERO else _ZERO
        leftover[p] = lo

        cfg = _normalize_cf_config(config_by_phase.get(p) or {})
        if cfg["enabled"] and lo > _ZERO and p not in excluded_phases:
            method = cfg["method"]
            formula = cfg["formula"]
            rvars = cfg["recipient_vars"]
            # Recurring-only phases are never carry-forward recipients.
            subsequent = [q for q in ordered[i + 1:] if q not in excluded_phases]
            if method == CF_TIME:
                # POOL family (frequency-based): the leftover is NOT applied to any
                # phase — it becomes a dated installment schedule consumed later at
                # invoicing. phase_received is deliberately left untouched.
                from app.utilities import cf_pool
                _, p_end = phase_dates.get(p, (None, None))
                p_start, p_end_proj = (project_bounds or (None, None))
                # Contract-relative pool buckets (bug #325): anchor on the
                # project start so the schedule follows the contract, not the
                # calendar.
                installments = cf_pool.build_installments(
                    lo, p_start, p_end_proj, p_end, cfg["frequency"], anchor=p_start)
                if installments:
                    pool[p] = installments
                    carried_out[p] = _round_money(
                        sum((x["amount"] for x in installments), _ZERO))
            elif method == CF_PHASE and subsequent:
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
        "pool": pool,
    }
