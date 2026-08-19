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
    """Fallback when contract-mgmt is unreachable or returns an error.

    ``compliance: None`` — same convention the upstream `_summarise` now
    uses when there's no data — so the FE renders a distinct "not
    available" state instead of a misleading "0% compliance."
    """
    return {
        "available":  False,
        "data_state": "service_down",
        "compliance": None,
        "met":        0,
        "breached":   0,
        "evaluated":  0,
        "pending":    0,
    }


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

    def trigger_activity_completion(
        self, activity_id: str, bearer_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fire the "activity completed → evaluate all its SLAs" workflow
        on contract-management.

        Best-effort — a failure here MUST NOT block the activity's own
        completion. The contract-mgmt endpoint auto-evaluates every
        date-derivable SLA and emails project + activity owners for the
        rest (SLAs that need manually-recorded observations).

        ``bearer_token`` is the completing user's raw ``Authorization``
        header value (``"Bearer <jwt>"``). It is forwarded so contract-mgmt's
        leave-backed auto-providers (e.g. SLA-007 resource availability) can
        source their observation from leave-management; when absent, contract
        omits it and those SLAs fall back to the manual-observation email.

        Returns the per-mapping summary contract-mgmt produced, or None
        if the call failed / the client is disabled.
        """
        if not self.enabled:
            return None
        headers = {"Authorization": bearer_token} if bearer_token else {}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/v3/sla-compliance/"
                    f"activities/{activity_id}/on-complete",
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "SLA on-complete trigger failed for activity %s: %s",
                activity_id, exc,
            )
            return None
        if resp.status_code >= 400:
            logger.warning(
                "SLA on-complete non-2xx for %s: %s %s",
                activity_id, resp.status_code, resp.text[:200],
            )
            return None
        body = resp.json()
        return body.get("data", body) if isinstance(body, dict) else body

    @staticmethod
    def combine(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Roll several per-project summaries into one (org / single-org).

        Mirrors contract-mgmt's ``_summarise`` — emits ``data_state`` and
        ``compliance: None`` when nothing has been evaluated, so the
        organisation rollup card can render "No SLA data yet" instead
        of "0% compliant".
        """
        met      = sum(int(s.get("met") or 0) for s in summaries)
        breached = sum(int(s.get("breached") or 0) for s in summaries)
        pending  = sum(int(s.get("pending") or 0) for s in summaries)
        denom    = met + breached
        if not summaries:
            data_state = "no_data"
        elif denom == 0:
            data_state = "awaiting_observations"
        elif pending > 0:
            data_state = "partial"
        else:
            data_state = "ready"
        return {
            "available":  any(s.get("available") for s in summaries),
            "data_state": data_state,
            "compliance": round(met * 100 / denom) if denom else None,
            "met":        met,
            "breached":   breached,
            "pending":    pending,
        }
