"""HTTP client for the user-management authorization decision surface.

This service is a pure Policy Enforcement Point: it no longer resolves
permissions from users.* itself. On each authed request the middleware
forwards the caller's ``Authorization`` header to user-management's
``GET /api/v3/authz/context`` and enforces locally against the response.

The caller's token is forwarded verbatim — NO service-account substitution
(that would bypass user-management's own checks). A 401 means the token is
anonymous / expired / revoked; any other failure raises so the middleware
can fail closed.
"""
from __future__ import annotations

from typing import Optional

import httpx

from app.config import settings
from app.utilities.logger import get_logger


logger = get_logger(__name__)


class UserMgmtClient:
    """Stateless wrapper around user-management's /authz/context endpoint."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        raw = base_url if base_url is not None else getattr(
            settings, "user_management_service_url", None
        )
        self.base_url = (raw or "").rstrip("/")
        self.timeout = float(
            timeout if timeout is not None
            else getattr(settings, "user_management_service_timeout_seconds", 5.0)
        )

    def fetch_authz_context(self, authorization: str) -> Optional[dict]:
        """Return the resolved authz context dict, or None if the token is
        anonymous/invalid (HTTP 401) or no user-management URL is configured.

        Raises ``httpx.HTTPError`` on connection failure / non-401 error so
        the caller can fail closed.
        """
        if not self.base_url:
            return None
        if not authorization:
            return None

        url = f"{self.base_url}/api/v3/authz/context"
        headers = {"Authorization": authorization, "Accept": "application/json"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)

        if resp.status_code == 401:
            return None
        resp.raise_for_status()

        body = resp.json()
        # user-management HAL-wraps payloads as {data, message, error, status}.
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body
