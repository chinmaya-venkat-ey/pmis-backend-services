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

from typing import Dict, List

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
