"""HTTP client for pmis-leave-management — used by Phase C's NpqpService.

Two things NpqpService needs from leave-mgmt:

  1. **F (planned/actual quarterly staff cost)** — per-resource per-month
     "cost" figure via ``GET /api/attendance/cost/monthly``. Leave-mgmt
     already folds paid-leave / half-day / relaxation deductions into
     that number per RFP §5.24-5.25, so NpqpService just sums it across
     resources and months.

  2. **Per-resource leave settlement** (optional) via
     ``GET /api/attendance/quarterly-leave``.

Auth — **JWT-forwarding**. This client does NOT hold service-account
credentials. Every method requires a ``bearer_token`` — the JWT of the
user who initiated the request. The token is forwarded verbatim to
leave-mgmt, which validates it against user-mgmt introspect.

Since every path that reaches contract-mgmt is user-initiated (no cron
in the event-driven model), there's always a caller JWT available. If
one isn't supplied, the client soft-fails to ``None`` — settlement
service then marks the quarter blocked with a clear reason.

Failures are LOGGED, not raised.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


class LeaveManagementClient:
    """Thin sync httpx wrapper around leave-mgmt's cost + leave endpoints.

    Stateless — safe to construct per request. No credentials, no cache.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        raw = base_url or settings.leave_management_base_url or ""
        self._base_url = raw.rstrip("/") if raw else ""
        self._timeout = timeout_seconds or settings.leave_management_timeout_seconds

    # ----------------------------------------------------------------- HTTP

    def _get(
        self,
        path: str,
        params: Dict[str, Any],
        bearer_token: Optional[str],
    ) -> Optional[Any]:
        """Forward the caller's JWT to leave-mgmt. Returns parsed JSON or
        None on any failure — callers degrade cleanly."""
        if not self._base_url:
            logger.info("LeaveManagementClient: leave_management_base_url unset — "
                        "NPQP fetch skipped for %s", path)
            return None
        if not bearer_token:
            logger.info(
                "LeaveManagementClient: no bearer_token forwarded — "
                "NPQP fetch skipped for %s. In the no-cron / event-driven "
                "model every trigger must carry the caller's JWT.",
                path,
            )
            return None
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            logger.warning("leave-mgmt unreachable at %s: %s", path, exc)
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code == 401:
            logger.warning(
                "leave-mgmt 401 on %s — caller's JWT is missing/expired/revoked. "
                "Ask the user to re-authenticate.", path,
            )
            return None
        if resp.status_code >= 400:
            logger.warning("leave-mgmt %s on %s: %s",
                           resp.status_code, path, resp.text[:200])
            return None
        try:
            return resp.json()
        except ValueError:
            logger.warning("leave-mgmt %s returned non-JSON body", path)
            return None

    # ----------------------------------------------------------------- public

    def get_monthly_cost(
        self,
        project_id: str,
        year: int,
        month: int,
        bearer_token: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """One row per resource with their computed monthly ``cost`` (₹).

        Sum of ``cost`` across resources is that month's F.
        None means "leave-mgmt unavailable" — NpqpService treats it as
        blocked and does NOT proceed with a partial NPQP.
        """
        body = self._get(
            "/api/attendance/cost/monthly",
            {"projectId": project_id, "year": year, "month": month},
            bearer_token=bearer_token,
        )
        return body if isinstance(body, list) else None

    def get_quarterly_leave(
        self,
        project_id: str,
        year: int,
        quarter: int,
        bearer_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """RFP §5.24.1 quarterly leave settlement per resource — used by
        the settlement UI, not by the NPQP arithmetic (that's already
        folded into ``get_monthly_cost``'s ``cost``)."""
        return self._get(
            "/api/attendance/quarterly-leave",
            {"projectId": project_id, "year": year, "quarter": quarter},
            bearer_token=bearer_token,
        )
