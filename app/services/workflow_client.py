"""HTTP client wrapper for the Activity Workflow Java microservice.

Java owns the canonical state machine. This client exposes two methods:

  * ``transition(...)`` — POSTs an action (SUBMIT / APPROVE / REJECT /
    UPDATE) to ``/activity-workflow/activities/process/_transition``.
    Returns Java's new state on success.

  * ``search_history(business_id)`` — GETs the per-activity transition
    history from ``/activity-workflow/activities/process/_search/ACTIVITY/{id}``.
    Returns the list of process-instance dicts verbatim.

Configuration knobs (``app.config.settings``):
  * ``workflow_service_url``           — base URL, e.g. ``http://localhost:8080``
  * ``workflow_service_timeout_seconds`` — outbound timeout
  * ``workflow_client``                — ``real`` (default if URL set) or ``mock``

In ``mock`` mode the client returns canned data so the inbox APIs can be
exercised without the Java service running. Mirrors the existing
``PMIS-user-management/app/services/notification_client.py`` pattern.

State translation (Java → FE-facing pill status) and role-code mapping
(PMIS → Java ``RequestInfo.roles``) live in ``app.utilities.workflow_state``
so callers don't reach into Java internals directly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# ── Java endpoint paths (only place we hard-code them) ─────────────────────
_TRANSITION_PATH = "/activity-workflow/activities/process/_transition"
_SEARCH_PATH_TEMPLATE = "/activity-workflow/activities/process/_search/ACTIVITY/{business_id}"

_BUSINESS_SERVICE = "ACTIVITY"
_MODULE_NAME = "activity-workflow"


class WorkflowClient:
    """Thin httpx wrapper. Stateless aside from the configured base URL +
    timeout. Safe to instantiate per request."""

    def __init__(self) -> None:
        self.base_url = (settings.workflow_service_url or "").rstrip("/")
        self.timeout = float(getattr(settings, "workflow_service_timeout_seconds", 10.0))
        configured_mode = (getattr(settings, "workflow_client", None) or "").lower()
        if configured_mode in ("mock", "real"):
            self.mode = configured_mode
        else:
            # Default: if a base URL is configured, treat as real; otherwise mock.
            self.mode = "real" if self.base_url else "mock"

    # ── transitions ──────────────────────────────────────────────────────

    def transition(
        self,
        *,
        business_id: str,
        action: str,
        request_info: Dict[str, Any],
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST a single transition. Returns the parsed JSON body on
        success; raises ``WorkflowServiceError`` otherwise."""
        body = {
            "RequestInfo": request_info,
            "ProcessInstances": [{
                "moduleName": _MODULE_NAME,
                "businessService": _BUSINESS_SERVICE,
                "businessId": business_id,
                "action": action,
                "comment": comment or "",
            }],
        }
        if self.mode == "mock":
            logger.info(
                "[MOCK WORKFLOW] transition action=%s businessId=%s",
                action, business_id,
            )
            # Mirror what Java would echo back: the request body + a synthetic
            # id. Callers use the response only for ``process_instance_id``.
            return {
                "ProcessInstances": [
                    {**body["ProcessInstances"][0],
                     "id": f"mock-{business_id}-{action.lower()}",
                     "auditDetails": {
                         "createdBy": (request_info.get("userInfo") or {}).get("uuid"),
                     }},
                ],
            }
        return self._post(_TRANSITION_PATH, body)

    # ── reads ────────────────────────────────────────────────────────────

    def search_history(self, business_id: str) -> List[Dict[str, Any]]:
        """GET the transition history for a single activity. Returns the
        raw ``ProcessInstances`` list (may be empty)."""
        if self.mode == "mock":
            logger.info("[MOCK WORKFLOW] search_history businessId=%s", business_id)
            return _mock_history(business_id)
        path = _SEARCH_PATH_TEMPLATE.format(business_id=business_id)
        body = self._get(path)
        return list(body.get("ProcessInstances") or [])

    # ── internals ────────────────────────────────────────────────────────

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=body)
        except httpx.HTTPError as exc:
            logger.error("Workflow POST failed: %s", exc)
            raise WorkflowServiceError(str(exc), details={"url": url}) from exc
        if resp.status_code >= 400:
            logger.error(
                "Workflow POST non-2xx: %s %s", resp.status_code, resp.text[:500]
            )
            raise WorkflowServiceError(
                f"Workflow service returned {resp.status_code}",
                details={"url": url, "status": resp.status_code,
                         "body": resp.text[:500]},
            )
        try:
            return resp.json() or {}
        except ValueError as exc:
            raise WorkflowServiceError("Invalid JSON from workflow service") from exc

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            logger.error("Workflow GET failed: %s", exc)
            raise WorkflowServiceError(str(exc), details={"url": url}) from exc
        if resp.status_code == 404:
            return {"ProcessInstances": []}
        if resp.status_code >= 400:
            logger.error(
                "Workflow GET non-2xx: %s %s", resp.status_code, resp.text[:500]
            )
            raise WorkflowServiceError(
                f"Workflow service returned {resp.status_code}",
                details={"url": url, "status": resp.status_code,
                         "body": resp.text[:500]},
            )
        try:
            return resp.json() or {}
        except ValueError as exc:
            raise WorkflowServiceError("Invalid JSON from workflow service") from exc


class WorkflowServiceError(Exception):
    """Raised when the Java workflow service is unreachable or errors out.
    The inbox service catches this and falls back to the cached tracker
    state so the FE never gets a 5xx just because Java is down."""

    def __init__(self, message: str, *, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ── Mock history generator (dev / tests only) ──────────────────────────────

def _mock_history(business_id: str) -> List[Dict[str, Any]]:
    """Returns a synthetic happy-path history mimicking Java's shape."""
    return [
        {
            "id": f"mock-{business_id}-1",
            "businessService": _BUSINESS_SERVICE,
            "businessId": business_id,
            "action": "SUBMIT",
            "moduleName": _MODULE_NAME,
            "comment": "Initial submission (mock)",
            "previousStatus": "READYFORAPPROVAL",
            "auditDetails": {
                "createdBy": "mock-vendor",
                "createdTime": 1779765482906,
            },
        },
    ]
