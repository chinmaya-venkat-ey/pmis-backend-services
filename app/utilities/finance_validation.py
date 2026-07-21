"""Server-side finance-page validation — the checks behind the FE "Validate"
button. Pure function over the built payment page + the project's live
milestones; no DB access here (the service loads the inputs).

Returns ``{"checks": [{"id", "label", "pass", "reason"}], "all_pass": bool}``.
``reason`` is empty when the check passes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TOL = Decimal("0.01")
_PHASE_TYPES = {"fixed", "resource_cost", "transaction_cost"}
_RECURRING = "recurring_cost"


def _d(x) -> Decimal:
    return Decimal(str(x)) if x is not None else _ZERO


def _recurring_only_phases(cost_items) -> set:
    """Phases whose cost is ENTIRELY recurring.

    Recurring money bills via its own dated frequency schedule, not via
    milestone payment-term %s, so such a phase is outside the billing sequence
    and must never be failed for a missing / blank payment-term %. Mixed phases
    (recurring + fixed/resource/transaction) still get the normal treatment.
    Mirrors ``payment_calc.recurring_only_phases``."""
    recurring: set = set()
    billing: set = set()
    for c in cost_items:
        phase = getattr(c, "phase", None)
        if phase is None:
            continue
        code = getattr(c, "cost_type_code", None)
        if code == _RECURRING:
            recurring.add(phase)
        elif code in _PHASE_TYPES:
            billing.add(phase)
    return recurring - billing


def run_finance_validation(page, active_milestone_ids: Iterable[str]) -> dict:
    checks: list = []

    def add(cid: str, label: str, ok: bool, reason: str = "") -> None:
        checks.append({"id": cid, "label": label, "pass": bool(ok), "reason": "" if ok else reason})

    totals = page.totals
    cost_items = list(page.cost_items or [])
    phases = list(page.phases or [])
    active_ids = set(active_milestone_ids or set())
    # Phases that carry only recurring cost — outside the billing sequence, so
    # the payment-term checks below skip them entirely.
    recurring_phases = _recurring_only_phases(cost_items)

    # ---- cost-level ------------------------------------------------------
    add("total-cost", "Total contract cost > 0",
        _d(totals.total_contract_cost) > _ZERO, "No cost items, or the total is 0.")

    add("has-cost-item", "At least one cost item added", len(cost_items) > 0,
        "The cost table is empty.")

    zero_rows = [c for c in cost_items if _d(c.total) <= _ZERO]
    add("cost-row-value", "Every cost row value > 0", not zero_rows,
        f"{len(zero_rows)} cost row(s) have a 0 / blank value.")

    bad_txn = [c for c in cost_items if c.cost_type_code == "transaction_cost"
               and (_d(c.per_transaction_cost) <= _ZERO or (c.planned_transactions or 0) <= 0)]
    add("txn-fields", "Transaction rows have per-transaction cost + planned count",
        not bad_txn, f"{len(bad_txn)} transaction row(s) missing perTransactionCost or plannedTransactions.")

    no_ms = [c for c in cost_items if c.cost_type_code in _PHASE_TYPES and not (c.milestone_ids)]
    add("row-milestone", "Every fixed/resource/transaction row has a milestone",
        not no_ms, f"{len(no_ms)} cost row(s) have no milestone attached.")

    bad_recurring = [c for c in cost_items if c.cost_type_code == "recurring_cost"
                     and not getattr(c, "frequency_code", None)]
    add("recurring-frequency", "Recurring rows have a distribution frequency",
        not bad_recurring, f"{len(bad_recurring)} recurring row(s) missing a frequency.")

    neg_tax = [c for c in cost_items if _d(c.tax_amount) < _ZERO]
    add("tax-nonneg", "Tax is not negative", not neg_tax,
        f"{len(neg_tax)} cost row(s) have a negative tax.")

    # ---- phase-level -----------------------------------------------------
    phases_with_cost = {c.phase for c in cost_items if c.phase}
    empty_phases = [str(p.phase) for p in phases if p.phase not in phases_with_cost]
    add("phase-cost-rows", "Every phase has at least one cost row", not empty_phases,
        f"Phase(s) with no cost row: {', '.join(empty_phases)}.")

    ot_total = _d(totals.one_time_cost)
    ot_alloc = sum((_d(p.one_time_allocated) for p in phases), _ZERO)
    add("one-time-distributed", "One-time cost fully distributed",
        ot_total == _ZERO or abs(ot_alloc - ot_total) <= _TOL,
        f"One-time allocated {ot_alloc} does not match the pool {ot_total}.")

    # ---- payment terms ---------------------------------------------------
    term_problems: list = []
    # "Last phase must total 100%" applies to the last BILLING phase. A
    # recurring-only phase is out of the sequence, so a trailing recurring
    # phase must not rob the real last phase of that rule.
    billing_phases = [p for p in phases if p.phase not in recurring_phases]
    last_billing = billing_phases[-1].phase if billing_phases else None
    for p in phases:
        terms = p.payment_terms or []
        # Recurring money is billed via its own dated frequency schedule, not
        # via milestone payment-term %s, so a recurring-only phase is outside
        # the billing sequence. Exempt it from the "% must total 100" rule
        # instead of flagging a phantom 0% shortfall on it. (The `not terms`
        # arm also covers any other phase that carries no billable term.)
        if p.phase in recurring_phases or not terms:
            continue
        tot = sum((_d(t.percent_of_payment) for t in terms), _ZERO)
        is_last = p.phase == last_billing
        cf_on = bool(getattr(p.carry_forward, "enabled", False))
        if tot > _HUNDRED + _TOL:
            term_problems.append(f"{p.phase} over-allocated ({tot}%)")
        elif is_last and abs(tot - _HUNDRED) > _TOL:
            term_problems.append(f"last phase {p.phase} totals {tot}%, must be 100%")
        elif (not is_last) and tot < _HUNDRED - _TOL and not cf_on:
            term_problems.append(f"{p.phase} totals {tot}% with no carry-forward (remainder is lost)")
    add("term-pct", "Payment-term % complete per phase (last = 100; shortfall must carry forward)",
        not term_problems, "; ".join(term_problems))

    # Recurring-only phases take no payment-term %, so a blank % there is not a
    # defect — skip them (they are the "% is blank" false failure).
    blank_pct = [str(t.milestone_id)
                 for p in phases if p.phase not in recurring_phases
                 for t in (p.payment_terms or [])
                 if t.percent_of_payment is None]
    add("term-not-blank", "No payment term % is blank", not blank_pct,
        f"{len(blank_pct)} term(s) have a blank %.")

    split_problems: list = []
    for p in phases:
        for t in (p.payment_terms or []):
            acts = t.activities or []
            if acts:
                s = sum((_d(a.percent_of_payment) for a in acts), _ZERO)
                if abs(s - _d(t.percent_of_payment)) > _TOL:
                    split_problems.append(f"{p.phase}/{t.milestone_id} split {s}% != term {_d(t.percent_of_payment)}%")
    add("activity-split", "Partial-payment activity splits match the term %",
        not split_problems, "; ".join(split_problems))

    bad_dates = [str(t.milestone_id) for p in phases for t in (p.payment_terms or [])
                 if t.start_date and t.end_date and t.start_date > t.end_date]
    add("milestone-dates", "Every term's start date <= end date", not bad_dates,
        f"{len(bad_dates)} term(s) have start after end.")

    bad_cycles = []
    if page.frequency_code:
        bad_cycles = [str(t.milestone_id) for p in phases for t in (p.payment_terms or [])
                      if t.cycle_count is not None and t.cycle_count <= 0]
    add("cycle-count", "Cycle counts are valid where a frequency is set", not bad_cycles,
        f"{len(bad_cycles)} term(s) have a non-positive cycle count.")

    # ---- milestones ------------------------------------------------------
    linked = {mid for c in cost_items for mid in (c.milestone_ids or [])}
    orphans = [mid for mid in active_ids if mid not in linked]
    add("milestone-linked", "Every active milestone is linked to a cost row", not orphans,
        f"{len(orphans)} milestone(s) have no cost / payment.")

    # ---- CCN -------------------------------------------------------------
    cap = _d(page.ccn.cap_percent) if page.ccn else _ZERO
    add("ccn-cap", "CCN cap % is between 0 and 100", _ZERO <= cap <= _HUNDRED,
        f"CCN cap is {cap}.")

    return {"checks": checks, "all_pass": all(c["pass"] for c in checks)}
