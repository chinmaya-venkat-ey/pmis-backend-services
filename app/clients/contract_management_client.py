"""HTTP client for pmis-contract-management — used by the payment page.

Fetches SLA quarterly-settlement rows so the payment page can render LD
deductions per quarter alongside the normal cost items.

Auth is bearer-forward: the caller (an authenticated FE user hitting
``GET /projects/{uuid}/payment-page``) already has a JWT; we just pass
it along. No service-account login flow here — the payment page is a
user-context read, and contract-mgmt gates it on the same JWT via its
existing auth middleware.

Soft-fail: any HTTP / parse error returns [] so a broken contract-mgmt
never breaks the payment page render. The FE shows the page without
the LD block; ops can still recover by hitting contract-mgmt directly.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


class ContractManagementClient:
    """Thin sync httpx wrapper. Stateless per request except for a small
    in-memory cache keyed on (project_id, bearer_hash) to avoid an
    identical round-trip per payment page render inside a 60 s window."""

    _CACHE_TTL_SECONDS = 60

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        raw = base_url or getattr(settings, "contract_management_base_url", None) or ""
        self._base_url = raw.rstrip("/") if raw else ""
        self._timeout = timeout_seconds or getattr(
            settings, "contract_management_timeout_seconds", 5.0,
        )
        self._cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ reads

    # ------------------------------------------------------------------ shared

    def _get(
        self, path: str, bearer_token: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Auth-forwarding GET returning the parsed 'data' payload or None
        on any failure. Callers decide how to shape their default."""
        if not self._base_url or not bearer_token:
            return None
        url = f"{self._base_url}{path}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(
                    url,
                    headers={"Authorization": f"Bearer {bearer_token}",
                             "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            logger.warning("contract-mgmt unreachable at %s: %s", path, exc)
            return None
        if resp.status_code >= 400:
            logger.info("contract-mgmt %s on %s — treating as no data",
                        resp.status_code, path)
            return None
        try:
            body = resp.json()
        except ValueError:
            return None
        return body.get("data") if isinstance(body, dict) else None

    # ------------------------------------------------------------------ settlement

    def list_settlements(
        self, project_id: str, bearer_token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return the raw items[] list of settlement rows, or [] on any
        failure. Empty list is a valid answer ("no settlement rows yet"),
        so callers should NOT treat [] as an error."""
        if not self._base_url or not bearer_token:
            return []
        cache_key = f"{project_id}|{hash(bearer_token)}"
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and time.monotonic() < entry[0]:
                return entry[1]
        url = f"{self._base_url}/api/v3/sla-compliance/projects/{project_id}/settlement"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {bearer_token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("contract-mgmt unreachable for %s: %s", project_id, exc)
            return []
        if resp.status_code >= 400:
            logger.info(
                "contract-mgmt %s on settlement fetch for %s — treating as no data",
                resp.status_code, project_id,
            )
            return []
        try:
            body = resp.json()
        except ValueError:
            logger.warning("contract-mgmt settlement response for %s was not JSON",
                           project_id)
            return []
        data = body.get("data") if isinstance(body, dict) else None
        items = (data.get("items") if isinstance(data, dict) else None) or []
        with self._lock:
            self._cache[cache_key] = (
                time.monotonic() + self._CACHE_TTL_SECONDS,
                items,
            )
        return items

    # ------------------------------------------------------------------ Track A (per-deliverable)

    def get_deliverable_lds(
        self, activity_id: str, bearer_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Track A LDs for ONE activity (single call)."""
        default = {"activityId": activity_id, "totalLdAmount": "0.00", "items": []}
        if not self._base_url or not bearer_token:
            return default
        data = self._get(
            f"/api/v3/sla-compliance/activities/{activity_id}/deliverable-lds",
            bearer_token,
        )
        return data if isinstance(data, dict) else default

    def get_deliverable_lds_by_activity(
        self, project_id: str, bearer_token: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Track A LDs for EVERY activity on a project (bulk — 1 HTTP call).

        Returns ``{activity_id: {activityId, totalLdAmount, items[]}}``.
        Activities with no Track A SLAs are absent from the dict.
        Soft-fails to ``{}`` on any error so the payment page still renders.
        """
        if not self._base_url or not bearer_token:
            return {}
        data = self._get(
            f"/api/v3/sla-compliance/projects/{project_id}/deliverable-lds",
            bearer_token,
        )
        if not isinstance(data, dict):
            return {}
        by = data.get("byActivity")
        return by if isinstance(by, dict) else {}
