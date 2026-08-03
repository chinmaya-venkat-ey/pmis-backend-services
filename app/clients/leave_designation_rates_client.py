"""HTTP client for the Java leave-management designation-rates service (:8019).

Fetches per-designation, per-contract-year MONTHLY rate cards used to cost a
resource-based activity's planned resources:

    GET {base}/api/designation-rates?projectId=&organisationId=
    -> [ { "id", "role", "projectId", "organisationId",
           "rateCardByYear": { "Year-1": <monthlyRate>, ... } }, ... ]

The response is a plain JSON array (NOT wrapped in a ``data`` envelope).

Bearer-forward (the caller's JWT is passed through), soft-fail (any HTTP/parse
error -> [] so rates resolve to 0 and the payment page still renders), with a
small per-``(project, org, bearer)`` TTL cache to avoid re-fetching within one
payment-page render.

The live service (10.1.131.199:8019) is NOT in the local harness, so
``leave_management_base_url == "mock"`` returns a built-in canned rate card for
local verification.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger

logger = get_logger(__name__)

# Canned rates for local-harness testing (leave_management_base_url == "mock").
# ~7%/yr escalation, mirroring the shape the live service returns.
_MOCK_RATE_CARDS: List[Dict[str, Any]] = [
    {"role": "Principal Architect",
     "rateCardByYear": {"Year-1": 198434, "Year-2": 211982, "Year-3": 228161,
                         "Year-4": 242376, "Year-5": 257587, "Year-6": 273863, "Year-7": 291278}},
    {"role": "Program Manager",
     "rateCardByYear": {"Year-1": 150000, "Year-2": 160500, "Year-3": 171735,
                         "Year-4": 183756, "Year-5": 196619, "Year-6": 210382, "Year-7": 225109}},
    {"role": "Application Security Engineer",
     "rateCardByYear": {"Year-1": 127481, "Year-2": 136064, "Year-3": 146928,
                         "Year-4": 155457, "Year-5": 164584, "Year-6": 174349, "Year-7": 184798}},
]


class LeaveDesignationRatesClient:
    """Thin sync httpx wrapper. Stateless per request except a small in-memory
    cache keyed on ``(project_id, org_id, bearer_hash)``."""

    _CACHE_TTL_SECONDS = 60

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        raw = base_url or getattr(settings, "leave_management_base_url", None) or ""
        self._raw = raw.strip()
        self._base_url = self._raw.rstrip("/") if self._raw else ""
        self._timeout = timeout_seconds or getattr(
            settings, "leave_management_timeout_seconds", 5.0,
        )
        self._cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    @property
    def is_mock(self) -> bool:
        return self._raw.lower() == "mock"

    def fetch_designation_rates(
        self, project_id: str, org_id: Optional[str],
        bearer_token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Rate-card rows for ``(project_id, org_id)``, or [] on any failure.
        [] is a valid answer (no cards) — callers must NOT treat it as an error
        (rates then resolve to 0)."""
        if self.is_mock:
            return _MOCK_RATE_CARDS
        if not self._base_url or not project_id:
            return []
        cache_key = f"{project_id}|{org_id}|{hash(bearer_token)}"
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and time.monotonic() < entry[0]:
                return entry[1]
        params = {"projectId": project_id}
        if org_id:
            params["organisationId"] = org_id
        url = f"{self._base_url}/api/designation-rates"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(
                    url, params=params,
                    headers={"Authorization": f"Bearer {bearer_token}",
                             "Accept": "application/json"} if bearer_token else
                            {"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            logger.warning("leave-mgmt designation-rates unreachable for %s/%s: %s",
                           project_id, org_id, exc)
            return []
        if resp.status_code >= 400:
            logger.info("leave-mgmt %s on designation-rates for %s/%s — no data",
                        resp.status_code, project_id, org_id)
            return []
        try:
            body = resp.json()
        except ValueError:
            logger.warning("leave-mgmt designation-rates for %s was not JSON", project_id)
            return []
        rows = body if isinstance(body, list) else []
        with self._lock:
            self._cache[cache_key] = (time.monotonic() + self._CACHE_TTL_SECONDS, rows)
        return rows
