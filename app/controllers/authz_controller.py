"""AuthzController — HTTP adapter for the `/api/v3/authz/*` decision surface.

Two surfaces:
  - ``get_context`` (enforcement): the resolved permission/scope facts for
    the caller's token. Thin wrapper over the ONE canonical resolver
    (``RbacRepository``) — no new resolution logic.
  - ``list_users`` (discovery): "WHICH users match this RBAC predicate?" for
    pickers / list-scoping. user-svc answers the RBAC half; the caller
    supplies its own resource facts (vendor/division/project ids) and unions
    the results locally.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from app.core.errors import ValidationError
from app.repositories.authz_query_repository import AuthzQueryRepository
from app.repositories.rbac_repository import RbacRepository
from app.schemas.authz import AuthzContextResponse, AuthzUserSummary


class AuthzController:
    def __init__(
        self,
        rbac: RbacRepository,
        query: Optional[AuthzQueryRepository] = None,
    ):
        self.rbac = rbac
        self.query = query

    # ------------------------------------------------------------------ enforcement

    def get_context(
        self, *, user_id: str, vendor_id: Optional[str],
    ) -> AuthzContextResponse:
        """Resolve the caller's full authorization context.

        Returns the GLOBAL flat code set + the per-scope map (with the
        vendor->project projection already applied by the resolver).
        """
        perms = self.rbac.effective_permissions_for_user(user_id)
        scoped = self.rbac.effective_permissions_by_scope(user_id)

        scoped_out: Dict[str, List[str]] = {}
        for (kind, scope_id), codes in scoped.items():
            key = kind if scope_id is None else f"{kind}:{scope_id}"
            scoped_out[key] = sorted(codes)

        return AuthzContextResponse(
            user_id=user_id,
            vendor_id=vendor_id,
            permissions=sorted(perms),
            scoped=scoped_out,
        )

    # ------------------------------------------------------------------ discovery

    def list_users(
        self,
        *,
        project_id: Optional[str] = None,
        vendor_ids: Optional[Sequence[str]] = None,
        divisions: Optional[Sequence[str]] = None,
        role: Optional[str] = None,
        org_id: Optional[str] = None,
        exclude_admin_tier: bool = False,
    ) -> List[AuthzUserSummary]:
        """Discovery query. Exactly ONE selector must be supplied:

          - ``project_id``  → users with a project-scoped role on it
          - ``vendor_ids``  → users with an org-scoped role on those vendors
          - ``divisions``   → users whose ``users.division`` is in the set

        ``role`` optionally narrows the project/org selectors to one role
        (e.g. ``org_admin``). With the ``divisions`` selector, supplying
        ``role`` switches to the intersection "users in these divisions who
        ALSO hold ``role``" (Bug #226), and ``org_id`` further restricts those
        to one organization (``users.vendor_id``) — e.g. UIDAI.
        ``exclude_admin_tier`` drops admin/super_admin tier users (the
        C5-correct definition lives in user-svc).
        """
        vendor_ids = list(vendor_ids or [])
        divisions = list(divisions or [])
        selectors = [bool(project_id), bool(vendor_ids), bool(divisions)]
        if sum(selectors) != 1:
            raise ValidationError(
                "Provide exactly one of: project_id, vendor_id, division",
                details={
                    "project_id": project_id,
                    "vendor_id": vendor_ids,
                    "division": divisions,
                },
            )
        if self.query is None:  # pragma: no cover - wiring guard
            raise ValidationError("Discovery query backend not configured")

        if project_id:
            users = self.query.users_by_project_role(project_id, role)
        elif vendor_ids:
            # "Users of the org" = home-vendor membership (users.vendor_id),
            # which is how users actually belong to an org (Bug #142). A
            # supplied role keeps the narrower org-scoped-role-holder semantics
            # (e.g. role=org_admin).
            users = (
                self.query.users_by_org_role(vendor_ids, role) if role
                else self.query.users_in_vendors(vendor_ids)
            )
        elif role:
            # Bug #226: division ∩ role (+ optional org), used by the
            # Manage-Team candidate pickers.
            users = self.query.users_by_division_role(divisions, role, vendor_id=org_id)
        else:
            users = self.query.users_by_division(divisions)

        if exclude_admin_tier:
            admin_ids = self.query.admin_tier_user_ids()
            users = [u for u in users if u.id not in admin_ids]

        roles_by_id = self.query.roles_by_user_ids([u.id for u in users])

        out = [
            AuthzUserSummary(
                id=u.id,
                login=u.login,
                email=u.email,
                full_name=u.full_name,
                vendor_id=u.vendor_id,
                division=u.division,
                roles=roles_by_id.get(u.id, []),
            )
            for u in users
        ]
        return sorted(out, key=lambda x: (x.login or ""))

    def list_assignable_users(
        self, *, project_id: str, role: str,
    ) -> List[AuthzUserSummary]:
        """Manage-Team picker: the role-tiered candidate pool for assigning
        ``role`` on ``project_id``, scoped to the project's org (vendor) — one
        self-contained call per dropdown.

          * ``project_admin`` → the org's project_admins + org_admins
          * ``project_member`` → the org's project_members

        See ``AuthzQueryRepository.users_assignable_to_project``.
        """
        if role not in ("project_admin", "project_member"):
            raise ValidationError(
                "role must be 'project_admin' or 'project_member'",
                details={"role": role},
            )
        if self.query is None:  # pragma: no cover - wiring guard
            raise ValidationError("Discovery query backend not configured")

        users = self.query.users_assignable_to_project(project_id, role)
        roles_by_id = self.query.roles_by_user_ids([u.id for u in users])
        out = [
            AuthzUserSummary(
                id=u.id,
                login=u.login,
                email=u.email,
                full_name=u.full_name,
                vendor_id=u.vendor_id,
                division=u.division,
                roles=roles_by_id.get(u.id, []),
            )
            for u in users
        ]
        return sorted(out, key=lambda x: (x.login or ""))
