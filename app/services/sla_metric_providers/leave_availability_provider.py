"""SLA007 auto-provider — per-resource business-days AND hours logged per month.

Sources the compound observation ``{"resource_business_days": bd,
"resource_logged_hours": hrs}`` from the (stub) leave-management availability
feed. SLA007 is scored COMBINED (worst severity across the two metrics), so the
value is a dict keyed by both metric_keys.

**Interim aggregation:** SLA007's thresholds are per-resource **per-month**
(>=16 business-days AND >=144 hours in a month), but the evaluation model scores
one observation per mapping (no per-resource / per-month fan-out yet). So every
(resource, month) figure in the quarter is reduced to the single **worst** one
(lowest business-days, tie-broken by lowest hours) — one real monthly figure,
scored as the mapping's observation. This correctly flags whether a breach
occurred and at what severity; it does NOT multiply LD across every breaching
resource-month. When per-(resource,month) LD fan-out is added, this provider
should emit one observation per resource-month instead.

STUB: the feed shape is a placeholder pending the real leave-mgmt contract
(see ``LeaveManagementClient.get_availability``). Inert (returns ``None``) unless
the leave base URL + a bearer are configured.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from app.clients.leave_management_client import LeaveManagementClient
from app.services.sla_metric_providers.base import (
    MetricProvider,
    ProviderContext,
    months_of_quarter,
)
from app.utilities.logger import get_logger

logger = get_logger(__name__)

_BD_KEY = "resource_business_days"
_HRS_KEY = "resource_logged_hours"


def _num(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


class LeaveAvailabilityProvider(MetricProvider):
    produces = frozenset({_BD_KEY, _HRS_KEY})

    def __init__(self, client: Optional[LeaveManagementClient] = None) -> None:
        self._client = client or LeaveManagementClient()

    def provide(self, ctx: ProviderContext) -> Optional[Dict[str, Decimal]]:
        if not ctx.project_id or not ctx.bearer_token:
            return None  # inert without a project + a forwardable JWT

        # Thresholds are monthly, so evaluate each (resource, month) figure and
        # keep the WORST (lowest business-days, tie-broken by lowest hours) —
        # never sum across months.
        worst: Optional[Tuple[Decimal, Decimal]] = None
        for year, month in months_of_quarter(ctx.quarter):
            rows = self._client.get_availability(
                ctx.project_id, year, month, bearer_token=ctx.bearer_token,
            )
            if rows is None:
                return None  # feed unavailable/unbuilt → fall back to manual
            for r in rows:
                # contract-align: confirm these field names with leave-mgmt.
                bd = _num(r.get("businessDaysPresent")) or Decimal("0")
                hrs = _num(r.get("hoursLogged")) or Decimal("0")
                if worst is None or (bd, hrs) < worst:
                    worst = (bd, hrs)

        if worst is None:
            return None
        return {_BD_KEY: worst[0], _HRS_KEY: worst[1]}
