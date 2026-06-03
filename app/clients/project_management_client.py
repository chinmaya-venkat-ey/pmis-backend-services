"""Client for pmis-project-management.

The contract-management service needs the *project_id* of an activity at
evaluation time (to load the project's severity_master and ld_bands).
That information lives in pmis-project-management; we resolve it via the
public HTTP API, forwarding the caller's bearer token so the upstream
service runs its own RBAC checks.

Design notes:

* **Sync httpx.** Routes are sync (FastAPI sync handlers). Using `httpx.Client`
  keeps the call simple — no event-loop juggling.
* **5-minute in-memory cache** keyed on activity_id. Activity → project mapping
  is effectively immutable in practice (activities don't reparent), so cache
  hits are safe within a short TTL.
* **Soft failure.** If project-management is unreachable, returns None and the
  evaluator falls back to RFP defaults. Evaluation should not break because a
  sibling service is down.
* **No new auth model.** Forwards the inbound Authorization header verbatim;
  user-svc-issued JWTs are valid across every service that shares the
  ``SECRET_KEY``.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


class ProjectManagementUnavailable(RuntimeError):
    """Raised when project-management returns an unexpected 5xx / network error.

    The evaluator catches this and continues with RFP defaults.
    """


class ProjectManagementClient:
    """Thin sync HTTP client with a short in-memory cache.

    One instance is fine per process (httpx connection pooling handles
    concurrency); we expose it as a FastAPI singleton dependency.
    """

    CACHE_TTL_SECONDS = 300  # 5 minutes — activities rarely change project.

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self._base_url = (base_url or settings.project_management_base_url).rstrip("/")
        self._timeout = timeout_seconds or settings.project_management_timeout_seconds
        self._cache: Dict[str, tuple[float, Optional[Dict[str, Any]]]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def get_activity(
        self,
        activity_id: str,
        bearer_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch an activity dict.

        Returns the raw ``data`` envelope from project-management, or None
        if the activity doesn't exist (404). Raises ``ProjectManagementUnavailable``
        on 5xx / network errors so the caller can decide how to degrade.
        """
        cached = self._cache_get(activity_id)
        if cached is not None:
            return cached

        # The pmis-project-management service mounts its routers under /api/v3.
        # When fronted by the VM's nginx the path is /projects/api/v3/activities/{id};
        # base_url already includes the /projects prefix.
        url = f"{self._base_url}/api/v3/activities/{activity_id}"
        headers: Dict[str, str] = {"Accept": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("project-management unreachable for %s: %s", activity_id, exc)
            raise ProjectManagementUnavailable(str(exc)) from exc

        if response.status_code == 404:
            self._cache_set(activity_id, None)
            return None
        if response.status_code >= 500:
            logger.warning(
                "project-management %s on %s: %s",
                response.status_code, activity_id, response.text[:200],
            )
            raise ProjectManagementUnavailable(
                f"upstream HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            # 401/403 mean we don't have permission to read this activity.
            # Treat as "no data" rather than a hard failure so the evaluator
            # can still produce a result with RFP defaults.
            logger.info(
                "project-management %s on %s — proceeding without prefill",
                response.status_code, activity_id,
            )
            return None

        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return None

        self._cache_set(activity_id, data)
        return data

    def get_activity_project_id(
        self,
        activity_id: str,
        bearer_token: Optional[str] = None,
    ) -> Optional[str]:
        """Convenience: extract ``project_id`` from the activity dict."""
        activity = self.get_activity(activity_id, bearer_token=bearer_token)
        if activity is None:
            return None
        # The API uses camelCase on the wire; accept either form for safety.
        return activity.get("projectId") or activity.get("project_id")

    # ------------------------------------------------------------------ cache

    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.monotonic():
                self._cache.pop(key, None)
                return None
            return value

    def _cache_set(self, key: str, value: Optional[Dict[str, Any]]) -> None:
        with self._lock:
            self._cache[key] = (time.monotonic() + self.CACHE_TTL_SECONDS, value)

    def invalidate(self, activity_id: Optional[str] = None) -> None:
        """Drop a specific entry, or the whole cache when called with None."""
        with self._lock:
            if activity_id is None:
                self._cache.clear()
            else:
                self._cache.pop(activity_id, None)
