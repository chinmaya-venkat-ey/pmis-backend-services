"""HTTP client for the dashboard's SLA blocks, sourced from
PMIS-contract-management's compliance aggregates.

Contract-management owns SLA evaluation and exposes read aggregates:
  GET /api/v3/sla-compliance/summary            -> global {compliance,met,breached}
  GET /api/v3/sla-compliance/projects/{id}      -> per-project + breaches[]
  GET /api/v3/sla-compliance/by-project         -> {project_id: summary}  (X-Project-Ids)

Those reads are unauthenticated (contract-mgmt has no permission gates), so
no bearer is required. Degrades to ``available: false`` when the URL is
unset or a call fails — the dashboard never breaks because SLA is down.

The organisation rollup (slaByOrganization) is assembled HERE, since
project-management is the only service that knows project→vendor.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger

logger = get_logger(__name__)


def _sla_unavailable() -> Dict[str, Any]:
    return {"available": False, "compliance": 0, "met": 0, "breached": 0}


class SlaClient:
    def __init__(self) -> None:
        self.base_url = (getattr(settings, "contract_management_base_url", None) or "").rstrip("/")
        self.timeout = float(getattr(settings, "contract_management_timeout_seconds", 6.0))
        self.enabled = bool(self.base_url)

    def _get(self, path: str, headers: Optional[Dict[str, str]] = None) -> Optional[Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(f"{self.base_url}{path}", headers=headers or {})
        except httpx.HTTPError as exc:
            logger.warning("SLA fetch failed for %s: %s", path, exc)
            return None
        if resp.status_code >= 400:
            logger.warning("SLA non-2xx for %s: %s", path, resp.status_code)
            return None
        body = resp.json()
        return body.get("data", body) if isinstance(body, dict) else body

    def global_summary(self) -> Dict[str, Any]:
        if not self.enabled:
            return _sla_unavailable()
        return self._get("/api/v3/sla-compliance/summary") or _sla_unavailable()

    def project_detail(self, project_id: str) -> Dict[str, Any]:
        if not self.enabled:
            return {**_sla_unavailable(), "breaches": []}
        d = self._get(f"/api/v3/sla-compliance/projects/{project_id}")
        return d or {**_sla_unavailable(), "breaches": []}

    def by_projects(self, project_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """``{project_id: summary}`` for the given set (for org / single-org rollups)."""
        if not self.enabled or not project_ids:
            return {}
        d = self._get("/api/v3/sla-compliance/by-project",
                      headers={"X-Project-Ids": ",".join(project_ids)})
        return d if isinstance(d, dict) else {}

    def by_milestones(self, project_id: str) -> Dict[str, Dict[str, Any]]:
        """``{milestone_id: {compliance, met, breached, ldPercent}}`` for the
        cost page's per-milestone SLA + LD deduction."""
        if not self.enabled:
            return {}
        d = self._get(f"/api/v3/sla-compliance/projects/{project_id}/milestones")
        return d if isinstance(d, dict) else {}

    @staticmethod
    def combine(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Roll several per-project summaries into one (org / single-org)."""
        met = sum(int(s.get("met") or 0) for s in summaries)
        breached = sum(int(s.get("breached") or 0) for s in summaries)
        denom = met + breached
        return {
            "available": any(s.get("available") for s in summaries),
            "compliance": round(met * 100 / denom) if denom else 0,
            "met": met, "breached": breached,
        }
