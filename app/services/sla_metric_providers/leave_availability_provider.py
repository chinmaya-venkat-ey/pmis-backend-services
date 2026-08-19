"""SLA007 auto-provider — TEAM-average business-days AND hours per cycle.

Sources the compound observation ``{"resource_business_days": bd,
"resource_logged_hours": hrs}`` from leave-management's activity availability
report (``GET /api/attendance/report/availability/activity``), which returns a
per-cycle breakdown already aggregated across every resource on the activity
(``totalBusinessDays`` / ``totalPresentDays`` / ``totalWorkingHours`` +
``resourceCount``).

SLA007 ("minimum resource availability") requires >=16 business-days AND >=144
working-hours per monthly cycle. **Product decision:** availability is judged at
the **team level** — for each cycle we take the average PER RESOURCE
(cycle total ÷ ``resourceCount``) for BOTH metrics, so the whole team's
completion of the required hours/days is measured, rather than penalising on the
single worst individual resource.

SLA007 is scored COMBINED (worst severity across the two metrics) on ONE
observation per mapping, so across the quarter's cycles we keep the **worst
cycle** (lowest average business-days, tie-broken by lowest average hours) — the
monthly threshold is applied to the weakest month, never summed across months.
Cycles are activity-start-aligned, so only those falling inside the evaluated
quarter are considered.

Inert (returns ``None``) unless the leave base URL + a bearer are configured and
the mapping's activity has an availability report for the quarter — the runner
then falls through to the manual observation path.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from app.clients.leave_management_client import LeaveManagementClient
from app.services.sla_metric_providers.base import MetricProvider, ProviderContext
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


def _parse_date(v: Any) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


class LeaveAvailabilityProvider(MetricProvider):
    produces = frozenset({_BD_KEY, _HRS_KEY})

    def __init__(self, client: Optional[LeaveManagementClient] = None) -> None:
        self._client = client or LeaveManagementClient()

    def provide(self, ctx: ProviderContext) -> Optional[Dict[str, Decimal]]:
        activity_id = getattr(ctx.mapping, "activity_id", None)
        if not ctx.project_id or not activity_id or not ctx.bearer_token:
            return None  # inert without a project + activity + forwardable JWT

        report = self._client.get_activity_availability(
            ctx.project_id, activity_id, bearer_token=ctx.bearer_token,
        )
        if not isinstance(report, dict):
            return None  # feed unavailable / activity unknown → manual fallback

        qs, qe = ctx.quarter.quarter_start, ctx.quarter.quarter_end
        worst: Optional[Tuple[Decimal, Decimal]] = None
        for m in report.get("months") or []:
            # Cycles are activity-start-aligned; keep only those in this quarter.
            fd = _parse_date(m.get("fromDate"))
            if fd is not None and not (qs <= fd <= qe):
                continue
            rc = _num(m.get("resourceCount")) or Decimal("0")
            if rc <= 0:
                continue  # no resource contributed this cycle → not a real figure
            # Team average per resource for the cycle (judge the whole team's
            # completion of the required days/hours, not the worst individual).
            bd = (_num(m.get("totalBusinessDays")) or Decimal("0")) / rc
            hrs = (_num(m.get("totalWorkingHours")) or Decimal("0")) / rc
            if worst is None or (bd, hrs) < worst:
                worst = (bd, hrs)

        if worst is None:
            return None
        return {_BD_KEY: worst[0], _HRS_KEY: worst[1]}
