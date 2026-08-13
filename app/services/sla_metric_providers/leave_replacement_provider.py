"""SLA005 auto-provider — resource replacements per quarter.

Sources the scalar ``resource_replacements_count`` from the (stub) leave-mgmt
replacements feed for the mapping's project over the quarter window. SLA005 is
PER_UNIT_OVER_THRESHOLD-shaped (a baseline of 1 replacement is free; each extra
escalates), which the point_accumulation evaluator handles from this count.

STUB: the feed shape is a placeholder pending the real leave-mgmt contract
(see ``LeaveManagementClient.get_replacements``). Inert (returns ``None``) unless
the leave base URL + a bearer are configured.
"""
from __future__ import annotations

from typing import Any, Optional

from app.clients.leave_management_client import LeaveManagementClient
from app.services.sla_metric_providers.base import MetricProvider, ProviderContext
from app.utilities.logger import get_logger

logger = get_logger(__name__)


class LeaveReplacementProvider(MetricProvider):
    produces = frozenset({"resource_replacements_count"})

    def __init__(self, client: Optional[LeaveManagementClient] = None) -> None:
        self._client = client or LeaveManagementClient()

    def provide(self, ctx: ProviderContext) -> Optional[int]:
        if not ctx.project_id or not ctx.bearer_token:
            return None

        data: Any = self._client.get_replacements(
            ctx.project_id,
            ctx.quarter.quarter_start.isoformat(),
            ctx.quarter.quarter_end.isoformat(),
            bearer_token=ctx.bearer_token,
        )
        if data is None:
            return None
        # contract-align: accept either {"count": N} or a list of events.
        if isinstance(data, dict):
            count = data.get("count")
            try:
                return int(count) if count is not None else None
            except (ValueError, TypeError):
                return None
        if isinstance(data, list):
            return len(data)
        return None
