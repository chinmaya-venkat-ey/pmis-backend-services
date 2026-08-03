"""Resolve a resource-based activity's planned-resource cost from live rates.

Designation rate cards come from the leave-mgmt service (per project+org, a
monthly rate per contract year). An activity maps to ONE contract quarter → one
contract year (anchored on the project start), and that year's monthly rate
applies to its allocation rows. Cost per row = ``quantity × monthlyRate ×
duration`` (duration a flat number of months in [0,3]).

Pure resolution helpers only — the client fetch + org lookup live in the caller
(``LeaveDesignationRatesClient`` + the activity/payment services).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.utilities import cf_pool

_YEARLY = "yearly"


def _dec(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return v if isinstance(v, Decimal) else Decimal(str(v))


def cards_by_role(rate_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """``{ role -> rateCardByYear }`` from the Java designation-rates array."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rate_rows or []:
        role = r.get("role")
        card = r.get("rateCardByYear")
        if role and isinstance(card, dict):
            out[str(role)] = card
    return out


def contract_year_no(activity_start, project_start) -> int:
    """1-based contract year of an activity, anchored on the project start.
    Falls back to Year-1 when a date/anchor is missing."""
    if activity_start is None or project_start is None:
        return 1
    idx = cf_pool.bucket_index(activity_start, _YEARLY, anchor=project_start)
    if idx is None:
        return 1
    return max(1, idx + 1)


def rate_for_year(rate_card: Optional[Dict[str, Any]], year_no: int) -> Decimal:
    """Monthly rate for contract ``year_no`` from a ``rateCardByYear`` map,
    clamping to the nearest available year; empty/missing → 0."""
    if not rate_card:
        return Decimal("0")
    n = max(1, year_no)
    key = f"Year-{n}"
    if key in rate_card:
        return _dec(rate_card[key])
    years = [
        int(k.split("-", 1)[1])
        for k in rate_card
        if k.startswith("Year-") and k.split("-", 1)[1].isdigit()
    ]
    if not years:
        return Decimal("0")
    clamped = min(max(n, min(years)), max(years))
    return _dec(rate_card.get(f"Year-{clamped}"))


def row_cost(rate, quantity, duration) -> Decimal:
    """Cost of one allocation row = rate × quantity × duration, 2dp."""
    return (_dec(rate) * _dec(quantity) * _dec(duration)).quantize(Decimal("0.01"))
