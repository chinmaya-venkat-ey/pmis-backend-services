"""HTTP client for cross-service writes to PMIS-user-management.

Used by team-page save to bulk-replace project-scoped role assignments
(the orgUser section of the Manage Team page). Because user-mgmt's
``PUT /api/v3/projects/{uuid}/role-assignments`` enforces
``project_members:update`` against the caller, this client forwards the
caller's ``Authorization`` header verbatim — NO service-account token
substitution. Using a service token would bypass user-mgmt's RBAC and
turn project-mgmt into a privilege-escalation vector.

Mock mode (``USER_MANAGEMENT_CLIENT=mock``, or no ``USER_MANAGEMENT_SERVICE_URL``
configured) logs the intended call and returns success. Useful in dev / tests
where user-mgmt isn't running. Local writes proceed unchanged.

Failure handling: any non-2xx response, connection error, or timeout is
translated to ``UserMgmtUnavailableError`` (HTTP 502 to the original
caller), with the upstream status + body included in ``details``.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import httpx

from app.config import settings
from app.core.errors import UserMgmtUnavailableError
from app.utilities.logger import get_logger


logger = get_logger(__name__)


_MAX_UPSTREAM_BODY_BYTES = 2048   # truncation cap for error details
_STAGE_REPLACE_ROLE_ASSIGNMENTS = "replace_role_assignments"


class UserMgmtClient:
    """Stateless wrapper around user-mgmt's project role-assignment endpoint.

    Construct per request; the underlying ``httpx.Client`` is created
    inside each method call (no persistent pool — matches the pattern of
    the other clients in this service).
    """

    def __init__(self) -> None:
        self.base_url = (
            getattr(settings, "user_management_service_url", None) or ""
        ).rstrip("/")
        self.timeout = float(
            getattr(settings, "user_management_service_timeout_seconds", 5.0)
        )
        configured_mode = (
            getattr(settings, "user_management_client", None) or ""
        ).lower()
        if configured_mode in ("mock", "real"):
            self.mode = configured_mode
        else:
            self.mode = "real" if self.base_url else "mock"

    def fetch_authz_context(self, authorization: str) -> Optional[dict]:
        """GET user-management's /api/v3/authz/context for the caller's token.

        Returns the resolved authz context dict (user_id / permissions /
        scoped / vendor_id), or None when the token is anonymous/invalid
        (HTTP 401) or no user-management URL is configured. Raises
        ``httpx.HTTPError`` on connection failure / non-401 error so the
        auth middleware can fail closed.

        The caller's ``Authorization`` is forwarded verbatim — user-management
        re-validates the token (signature / expiry / revocation) and resolves
        the permission set itself (this service is a pure enforcement point).
        """
        if not self.base_url or not authorization:
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

    def fetch_users(
        self,
        *,
        authorization: str,
        project_id: Optional[str] = None,
        vendor_ids: Optional[List[str]] = None,
        divisions: Optional[List[str]] = None,
        role: Optional[str] = None,
        org_id: Optional[str] = None,
        exclude_admin_tier: bool = False,
    ) -> List[dict]:
        """Discovery query against user-management's /api/v3/authz/users.

        Exactly ONE selector must be supplied (project_id, vendor_ids, or
        divisions) — see the endpoint contract. With the ``divisions``
        selector, ``role`` selects users in those divisions who ALSO hold the
        role and ``org_id`` restricts them to one organization (Bug #226).
        Returns the list of user dicts (id / login / email / full_name /
        vendor_id / division / roles), or [] when no user-management URL /
        token is available.
        """
        if not self.base_url or not authorization:
            return []

        params: List[tuple] = []
        if project_id:
            params.append(("project_id", project_id))
        for v in (vendor_ids or []):
            params.append(("vendor_id", v))
        for d in (divisions or []):
            params.append(("division", d))
        if role:
            params.append(("role", role))
        if org_id:
            params.append(("org_id", org_id))
        if exclude_admin_tier:
            params.append(("exclude_admin_tier", "true"))

        url = f"{self.base_url}/api/v3/authz/users"
        headers = {"Authorization": authorization, "Accept": "application/json"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params, headers=headers)
        resp.raise_for_status()

        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            return (data.get("_embedded") or {}).get("elements") or []
        if isinstance(data, list):
            return data
        return []

    def replace_project_role_assignments(
        self,
        *,
        project_uuid: str,
        assignments_by_role: Dict[str, List[str]],
        authorization: str,
    ) -> None:
        """PUT user-mgmt's bulk-replace endpoint for one project.

        ``assignments_by_role`` shape: ``{role_name: [user_id, ...], ...}``.
        Roles not present in the dict are LEFT UNCHANGED on the upstream
        (per user-mgmt's documented semantics) — callers should pre-diff
        and only send the roles whose user sets actually changed.

        ``authorization`` is forwarded verbatim (the full header value,
        e.g. ``"Bearer eyJ..."``). Raises ``UserMgmtUnavailableError`` on
        any failure; the caller (TeamService.save_team_page) aborts the
        local write so partial state isn't persisted.

        In mock mode the call is logged and returns silently — local
        writes proceed as if the cross-service write succeeded.
        """
        if not authorization:
            # Defensive: route gate already enforced auth, so this should
            # never happen. If it does, surface as 502 (rather than 401)
            # since the missing header is a project-mgmt orchestration bug.
            raise UserMgmtUnavailableError(
                "Missing caller Authorization header for cross-service call to user-mgmt",
                details={"stage": _STAGE_REPLACE_ROLE_ASSIGNMENTS, "upstream_status": None},
            )

        if self.mode == "mock":
            logger.info(
                "user_mgmt_client[mock] replace_project_role_assignments "
                "project=%s roles=%s",
                project_uuid, sorted(assignments_by_role),
            )
            return

        url = f"{self.base_url}/api/v3/projects/{project_uuid}/role-assignments"
        body = {"assignments": {k: list(v) for k, v in assignments_by_role.items()}}
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.put(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning(
                "user_mgmt_client connection failure project=%s err=%s",
                project_uuid, exc,
            )
            raise UserMgmtUnavailableError(
                "User-management service is unreachable. "
                "Team-page save aborted; no changes were persisted.",
                details={
                    "stage": _STAGE_REPLACE_ROLE_ASSIGNMENTS,
                    "upstream_status": None,
                    "upstream_error": str(exc),
                },
            ) from exc

        if 200 <= resp.status_code < 300:
            return

        body_excerpt = (resp.text or "")[:_MAX_UPSTREAM_BODY_BYTES]
        logger.warning(
            "user_mgmt_client non-2xx project=%s status=%s body=%s",
            project_uuid, resp.status_code, body_excerpt,
        )
        raise UserMgmtUnavailableError(
            f"User-management service rejected the role-assignment write "
            f"(HTTP {resp.status_code}). Team-page save aborted; no changes "
            f"were persisted.",
            details={
                "stage": _STAGE_REPLACE_ROLE_ASSIGNMENTS,
                "upstream_status": resp.status_code,
                "upstream_body": body_excerpt,
            },
        )
