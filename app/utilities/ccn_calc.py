"""Pure-function calculators for project finance (Doc-finance).

All amounts are INR rupees as ``Decimal`` (matches the NUMERIC(18, 2)
columns on the projects / milestones / activities tables). No DB access,
no side effects — this module is a stand-alone helper used by the
finance summary endpoint and the milestone/activity cap check.

Calculation rules:

* ``ccn_cap_amount`` — when TPV > 0, ``TPV × ccn_cap_percent / 100``.
  When TPV == 0 the cap is 0 (finance dormant; see ``is_cap_active``).
* ``ccn_used`` — sum of ``ccn_value`` across every live milestone +
  activity with ``category='ccn'`` for the project.
* ``effective_value`` — ``TPV + ccn_used`` (final contract cost).
* ``total_project_value_incl_tax`` — derived on every response as
  ``TPV × (1 + tax_percent/100)``; never stored.
* ``ccn_used_percent`` — ``ccn_used / ccn_cap × 100``. ``None`` when the
  cap is dormant (TPV = 0) — Finance-page rows render "—" in that case.

The cap check (used by milestone_service / activity_service when adding
or updating a CCN row) is also expressed here so the two callers share
exactly one rule. See ``would_exceed_cap``.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_QUANTIZE = Decimal("0.01")


def _to_decimal(value) -> Decimal:
    """Coerce ``None``/int/float/str/Decimal → Decimal. NULL → 0."""
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round_money(value: Decimal) -> Decimal:
    """Round to 2dp (banker's-style not desired here; standard rounding
    matches what the FE displays via Indian-number formatting)."""
    return value.quantize(_QUANTIZE, rounding=ROUND_HALF_UP)


def is_cap_active(tpv_excl_tax) -> bool:
    """Cap enforcement is active only when TPV > 0. With TPV = 0 the
    project is treated as "finance dormant" and CCN adds bypass the cap
    check (any value is accepted)."""
    return _to_decimal(tpv_excl_tax) > _ZERO


def ccn_cap_amount(tpv_excl_tax, ccn_cap_percent) -> Decimal:
    """Cap amount in INR. Always returns a 2dp Decimal."""
    tpv = _to_decimal(tpv_excl_tax)
    pct = _to_decimal(ccn_cap_percent)
    if tpv <= _ZERO or pct < _ZERO:
        return _ZERO
    return _round_money(tpv * pct / _HUNDRED)


def total_project_value_incl_tax(tpv_excl_tax, tax_percent) -> Decimal:
    """Derived inclusive-tax value. Returned on every project response;
    never stored on the row."""
    tpv = _to_decimal(tpv_excl_tax)
    tax = _to_decimal(tax_percent)
    if tax <= _ZERO:
        return _round_money(tpv)
    return _round_money(tpv * (_HUNDRED + tax) / _HUNDRED)


def ccn_used_percent(ccn_used, ccn_cap) -> Optional[Decimal]:
    """``None`` when the cap is dormant (no division-by-zero); otherwise
    a 2dp Decimal percentage."""
    cap = _to_decimal(ccn_cap)
    used = _to_decimal(ccn_used)
    if cap <= _ZERO:
        return None
    return _round_money(used / cap * _HUNDRED)


def ccn_headroom(ccn_used, ccn_cap) -> Optional[Decimal]:
    """Remaining headroom (``cap - used``) when cap is active; ``None``
    when dormant."""
    cap = _to_decimal(ccn_cap)
    if cap <= _ZERO:
        return None
    return _round_money(cap - _to_decimal(ccn_used))


def effective_value(tpv_excl_tax, ccn_used) -> Decimal:
    """Base contract value + CCN used = final contract cost."""
    return _round_money(_to_decimal(tpv_excl_tax) + _to_decimal(ccn_used))


def would_exceed_cap(
    *, tpv_excl_tax, ccn_cap_percent, existing_ccn_used, new_ccn_value,
) -> bool:
    """Cumulative cap check used by milestone_service / activity_service
    when adding a new CCN row or updating an existing one (displacement
    rule: the caller pre-subtracts the row's prior value from
    ``existing_ccn_used`` before calling).

    Returns False (no cap violation) when TPV = 0 (cap dormant) or when
    ``existing_ccn_used + new_ccn_value <= cap``. Returns True otherwise.
    """
    if not is_cap_active(tpv_excl_tax):
        return False
    cap = ccn_cap_amount(tpv_excl_tax, ccn_cap_percent)
    projected = _to_decimal(existing_ccn_used) + _to_decimal(new_ccn_value)
    return projected > cap


def cap_exceed_details(
    *, tpv_excl_tax, ccn_cap_percent, existing_ccn_used, new_ccn_value,
) -> dict:
    """Structured payload for the 409 details when a cap-exceed is
    rejected. Always returns positive 2dp Decimals."""
    tpv = _to_decimal(tpv_excl_tax)
    pct = _to_decimal(ccn_cap_percent)
    used = _to_decimal(existing_ccn_used)
    attempted = _to_decimal(new_ccn_value)
    cap = ccn_cap_amount(tpv, pct)
    projected = used + attempted
    return {
        "cap": str(cap),
        "used": str(_round_money(used)),
        "attempted": str(_round_money(attempted)),
        "projected": str(_round_money(projected)),
        "overflow": str(_round_money(projected - cap)),
        "headroom_before": str(_round_money(max(cap - used, _ZERO))),
        "tpv_excl_tax": str(_round_money(tpv)),
        "ccn_cap_percent": str(_round_money(pct)),
    }
