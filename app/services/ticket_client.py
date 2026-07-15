"""HTTP client for the dashboard's tickets block, sourced from the Java
PMIS-Ticket-service (read-only).

That service has no organisation dimension and only single-value filters,
so instead of fanning out per project we pull ONE bounded ticket list and
compute every figure client-side — for the global dashboard, or filtered
to an organisation's project-id set. The caller's bearer token is
forwarded verbatim (the Java service validates it via user-svc
introspect).

Degrades to ``available: false`` when no URL is configured or on any
error/timeout — the dashboard must never fail because tickets are down.

Known gaps (Java service limitations, documented): priorities are P1–P3
only (P4 is surfaced with zero counts to keep the FE shape); there is no
ticket-age metric, so ``avgAgeDays`` is 0; ``resolved30d`` needs a
resolved-timestamp the list may not expose and is best-effort.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger

logger = get_logger(__name__)

# Hardcoded priority presentation (the Java service stores only the code).
_PRIORITY_META = [
    {"code": "P1", "label": "Critical", "color": "#e11d48"},
    {"code": "P2", "label": "High", "color": "#f97316"},
    {"code": "P3", "label": "Medium", "color": "#f59e0b"},
    {"code": "P4", "label": "Low", "color": "#22c55e"},
]
_OPEN_STATUSES = {"OPEN", "IN_PROGRESS", "PENDING"}
_CLOSED_STATUSES = {"RESOLVED", "CLOSED"}


def _unavailable() -> Dict[str, Any]:
    return {
        "available": False, "total": 0, "open": 0,
        "byPriority": [], "escalations": [],
        "highPriority": 0, "resolved30d": 0, "avgAgeDays": 0,
    }


class TicketClient:
    def __init__(self) -> None:
        self.base_url = (getattr(settings, "ticket_service_url", None) or "").rstrip("/")
        self.timeout = float(getattr(settings, "ticket_service_timeout_seconds", 6.0))
        self.cap = int(getattr(settings, "ticket_service_list_cap", 2000))
        self.enabled = bool(self.base_url)

    def _fetch_list(self, bearer: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        headers = {"Accept": "application/json"}
        if bearer:
            headers["Authorization"] = bearer
        url = f"{self.base_url}/tickets"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, params={"size": self.cap, "page": 0}, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("Ticket list fetch failed: %s", exc)
            return None
        if resp.status_code >= 400:
            logger.warning("Ticket list non-2xx: %s %s", resp.status_code, resp.text[:200])
            return None
        body = resp.json()
        tickets = body.get("tickets") or body.get("content") or []
        total = body.get("totalCount")
        if total is not None and total > len(tickets):
            logger.info("Ticket list truncated: got %s of %s (cap=%s)", len(tickets), total, self.cap)
        return tickets

    def summary(
        self, *, bearer: Optional[str] = None, project_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Tickets block. ``project_ids=None`` => global; a list => only
        tickets whose ``projectId`` is in that set."""
        if not self.enabled:
            return _unavailable()
        tickets = self._fetch_list(bearer)
        if tickets is None:
            return _unavailable()

        if project_ids is not None:
            wanted = set(project_ids)
            tickets = [t for t in tickets if (t.get("projectId") in wanted)]

        def _status(t):
            return (t.get("status") or "").upper()

        def _prio(t):
            return (t.get("priority") or "").upper()

        def _breached(t):
            return bool(t.get("slaBreached") if "slaBreached" in t else t.get("sla_breached"))

        total = len(tickets)
        open_n = sum(1 for t in tickets if _status(t) in _OPEN_STATUSES)
        breached = sum(1 for t in tickets if _breached(t))

        by_priority: List[Dict[str, Any]] = []
        for meta in _PRIORITY_META:
            grp = [t for t in tickets if _prio(t) == meta["code"]]
            g_open = sum(1 for t in grp if _status(t) in _OPEN_STATUSES)
            g_closed = sum(1 for t in grp if _status(t) in _CLOSED_STATUSES)
            by_priority.append({
                **meta, "total": len(grp), "open": g_open, "closed": g_closed,
            })
        p1_open = next((p["open"] for p in by_priority if p["code"] == "P1"), 0)
        p2_open = next((p["open"] for p in by_priority if p["code"] == "P2"), 0)

        escalations = [
            {"issue": "Critical tickets open", "count": p1_open, "severity": "high"},
            {"issue": "High-priority tickets open", "count": p2_open, "severity": "medium"},
            {"issue": "Tickets breaching SLA", "count": breached, "severity": "high"},
        ]

        return {
            "available": True,
            "total": total,
            "open": open_n,
            "byPriority": by_priority,
            "escalations": escalations,
            # extra fields consumed by the single-organisation view:
            "highPriority": p1_open,
            "resolved30d": 0,   # gap: no reliable resolved-timestamp in the list
            "avgAgeDays": 0,    # gap: service exposes no age metric
        }
