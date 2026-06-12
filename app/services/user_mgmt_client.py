"""HTTP client for the user-management authorization decision surface.

This service is a pure Policy Enforcement Point for RBAC: it no longer
resolves permissions from users.* itself. On each authed request the
middleware forwards the caller's ``Authorization`` header to
user-management's ``GET /api/v3/authz/context`` and enforces locally.

The caller's token is forwarded verbatim — NO service-account substitution.
A 401 means the token is anonymous / expired / revoked; any other failure
raises so the middleware can fail closed.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import httpx

from app.config import settings
from app.core.errors import ForbiddenError, UnauthorizedError, ValidationError
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

    def fetch_project_role_user_ids(
        self, *, authorization: str, project_id: str, role: str,
    ) -> List[str]:
        """Bug #128/#133: user IDs holding ``role`` on ``project_id``, via
        user-management's discovery endpoint (``GET /authz/users``). Used to
        populate a vendor's per-project role assignments in Org Management.

        Fail-soft: returns ``[]`` when no URL/token is configured or the call
        fails, so the vendor detail never breaks on a transient user-mgmt issue.
        """
        if not self.base_url or not authorization:
            return []
        url = f"{self.base_url}/api/v3/authz/users"
        params = {"project_id": project_id, "role": role}
        headers = {"Authorization": authorization, "Accept": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "user_mgmt_client discovery failure project=%s role=%s err=%s",
                project_id, role, exc,
            )
            return []
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            elements = (data.get("_embedded") or {}).get("elements") or []
        elif isinstance(data, list):
            elements = data
        else:
            elements = []
        return [u["id"] for u in elements if isinstance(u, dict) and u.get("id")]

    def replace_project_role_assignments(
        self, *, project_uuid: str, assignments_by_role: Dict[str, List[str]],
        authorization: str,
    ) -> None:
        """#128/#254: forward Org-Management's per-project role assignments to
        user-management's bulk-replace endpoint
        (``PUT /api/v3/projects/{id}/role-assignments``) — it owns
        ``users.user_role_assignments``.

        ``assignments_by_role``: ``{role_name: [user_id, ...]}``. Each listed
        role is fully REPLACED upstream; roles not present are left unchanged.
        The caller's token is forwarded verbatim so user-management enforces
        ``rbac:assign`` + the grant matrix. Raises (mapping the upstream
        status) on any non-2xx so the vendor PATCH surfaces the failure.
        """
        if not self.base_url:
            raise ValidationError(
                "user-management service URL not configured; cannot persist role "
                "assignments",
            )
        if not authorization:
            raise UnauthorizedError(
                "Missing caller Authorization for role-assignment forward",
            )
        url = f"{self.base_url}/api/v3/projects/{project_uuid}/role-assignments"
        headers = {
            "Authorization": authorization,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.put(
                    url, json={"assignments": assignments_by_role}, headers=headers,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "role-assignment forward connection error project=%s err=%s",
                project_uuid, exc,
            )
            raise ValidationError(
                f"Failed to persist role assignments for project {project_uuid} "
                f"(user-management unreachable)",
                details={"project_id": project_uuid, "upstream_status": None},
            )
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = {"message": resp.text[:200]}
            upstream_msg = (
                (detail.get("error") or {}).get("message")
                if isinstance(detail, dict) else None
            )
            base = (
                f"Role assignment rejected for project {project_uuid} "
                f"(user-management returned {resp.status_code})"
            )
            full = f"{base}: {upstream_msg}" if upstream_msg else base
            d = {
                "project_id": project_uuid,
                "upstream_status": resp.status_code,
                "upstream": detail,
            }
            if resp.status_code == 401:
                raise UnauthorizedError(full, details=d)
            if resp.status_code == 403:
                raise ForbiddenError(full, details=d)
            raise ValidationError(full, details=d)
