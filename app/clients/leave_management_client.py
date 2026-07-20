"""HTTP client for pmis-leave-management — used by Phase C's NpqpService.

Two things NpqpService needs from leave-mgmt:

  1. **F (planned/actual quarterly staff cost)** — per-resource per-month
     "cost" figure via ``GET /api/attendance/cost/monthly``. Leave-mgmt has
     already folded paid-leave / half-day / relaxation deductions into
     that number per RFP §5.24-5.25, so NpqpService just sums it across
     resources and months.

  2. **Per-resource leave settlement** (optional, for the settlement UI /
     audit) via ``GET /api/attendance/quarterly-leave``.

Auth is JWT bearer. NpqpService runs from the daily cron (no user
context), so this client owns a **service-account** login flow:

  * Reads ``settings.pmis_service_account_login`` +
    ``.pmis_service_account_password`` at construction.
  * Logs in via ``POST /users/api/v3/users/login`` +
    ``.../login/verify-otp`` (universal OTP for cron use).
  * Caches the access_token in-memory for its 2h TTL (JWT ``exp``).
  * On 401 from any downstream call, re-logs-in once and retries.

Failures are LOGGED, not raised — the settlement flow degrades to
"NPQP unavailable" rather than 500ing the cron.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


class LeaveManagementUnavailable(RuntimeError):
    """Raised when leave-mgmt is unreachable AND the caller wants to know.

    Most callers should let the client soft-fail (return None) instead.
    """


class LeaveManagementClient:
    """Thin sync httpx wrapper around leave-mgmt's cost + leave endpoints.

    Stateful — caches a service-account bearer in-memory.
    Construct once per process (FastAPI singleton dependency).
    """

    # Refresh bearer 5 minutes before it expires (JWT default TTL = 2h).
    _BEARER_TTL_SECONDS = 60 * 60 * 2 - 300

    def __init__(
        self,
        base_url: Optional[str] = None,
        user_mgmt_base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        raw = base_url or settings.leave_management_base_url or ""
        self._base_url = raw.rstrip("/") if raw else ""
        # User-mgmt lives at the same host under a different prefix (/users
        # on the deployed VM). Reuse its configured URL so we don't have to
        # thread a second env var. Fallback to blank → login won't be
        # attempted, calls fail-soft.
        um = user_mgmt_base_url or settings.user_management_service_url or ""
        self._user_mgmt_url = um.rstrip("/") if um else ""
        self._timeout = timeout_seconds or settings.leave_management_timeout_seconds

        self._lock = threading.Lock()
        self._bearer: Optional[str] = None
        self._bearer_expires_at: float = 0.0

    # ----------------------------------------------------------------- auth

    def _login(self) -> Optional[str]:
        """Return a fresh service-account bearer or None if it fails."""
        if not self._user_mgmt_url:
            logger.warning(
                "LeaveManagementClient: user_management_service_url not set — "
                "cannot obtain service-account bearer.",
            )
            return None
        login = settings.pmis_service_account_login
        password = settings.pmis_service_account_password
        if not login or not password:
            logger.warning(
                "LeaveManagementClient: PMIS_SERVICE_ACCOUNT_LOGIN / "
                "PMIS_SERVICE_ACCOUNT_PASSWORD not set — NPQP disabled.",
            )
            return None
        otp = settings.pmis_service_account_otp
        try:
            with httpx.Client(timeout=self._timeout) as client:
                # Step 1: username + password → either token pair or OTP required.
                r1 = client.post(
                    f"{self._user_mgmt_url}/api/v3/users/login",
                    json={"login": login, "password": password},
                )
                if r1.status_code >= 400:
                    logger.warning("service-account login failed: %s %s",
                                   r1.status_code, r1.text[:200])
                    return None
                body1 = r1.json().get("data", {})
                token = body1.get("access_token")
                if token:
                    return token
                # Step 2: OTP required → verify with universal OTP.
                ephemeral = body1.get("ephemeral_token")
                if not ephemeral:
                    logger.warning(
                        "service-account login: unexpected response shape %s",
                        list(body1.keys()),
                    )
                    return None
                r2 = client.post(
                    f"{self._user_mgmt_url}/api/v3/users/login/verify-otp",
                    json={"ephemeral_token": ephemeral, "code": otp},
                )
                if r2.status_code >= 400:
                    logger.warning(
                        "service-account OTP verify failed: %s %s",
                        r2.status_code, r2.text[:200],
                    )
                    return None
                token = r2.json().get("data", {}).get("access_token")
                return token
        except httpx.HTTPError as exc:
            logger.warning("service-account login network error: %s", exc)
            return None

    def _bearer_valid(self) -> Optional[str]:
        with self._lock:
            if self._bearer and time.monotonic() < self._bearer_expires_at:
                return self._bearer
        # Refresh outside the lock (avoid holding it during HTTP).
        fresh = self._login()
        if fresh is None:
            return None
        with self._lock:
            self._bearer = fresh
            self._bearer_expires_at = time.monotonic() + self._BEARER_TTL_SECONDS
        return fresh

    # ----------------------------------------------------------------- HTTP GET

    def _get(self, path: str, params: Dict[str, Any]) -> Optional[Any]:
        """Auth-forwarding GET that transparently re-logs-in on 401.

        Returns the parsed JSON body, or None on any failure so callers
        can degrade cleanly (settlement service treats None as "F
        unavailable, mark settlement as blocked_missing_npqp").
        """
        if not self._base_url:
            logger.info("LeaveManagementClient: leave_management_base_url unset — "
                        "NPQP fetch skipped for %s", path)
            return None
        bearer = self._bearer_valid()
        if bearer is None:
            return None
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, headers=headers, params=params)
                if resp.status_code == 401:
                    # Bearer expired mid-request; force re-login and retry once.
                    with self._lock:
                        self._bearer = None
                        self._bearer_expires_at = 0.0
                    bearer2 = self._bearer_valid()
                    if bearer2 is None:
                        return None
                    headers["Authorization"] = f"Bearer {bearer2}"
                    resp = client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            logger.warning("leave-mgmt unreachable at %s: %s", path, exc)
            return None
        if resp.status_code == 404:
            # 404 for a specific resource is a valid "no data" answer.
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
        self, project_id: str, year: int, month: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """One row per resource with their computed monthly `cost` (₹).

        Sum of the ``cost`` field across resources is that month's F.
        None means "leave-mgmt unavailable" — NpqpService treats it as
        blocked and does NOT proceed with a partial NPQP.
        """
        body = self._get("/api/attendance/cost/monthly", {
            "projectId": project_id, "year": year, "month": month,
        })
        if body is None:
            return None
        # Endpoint returns a bare list, not an envelope.
        return body if isinstance(body, list) else None

    def get_quarterly_leave(
        self, project_id: str, year: int, quarter: int,
    ) -> Optional[Dict[str, Any]]:
        """RFP §5.24.1 quarterly leave settlement: paid / unpaid / sandwich
        per resource. Used by the settlement UI, not by the NPQP arithmetic
        (that's already folded into ``get_monthly_cost``'s ``cost`` field)."""
        return self._get("/api/attendance/quarterly-leave", {
            "projectId": project_id, "year": year, "quarter": quarter,
        })
