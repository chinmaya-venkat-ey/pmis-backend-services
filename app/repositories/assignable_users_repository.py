"""Per-project user pickers.

Two read surfaces:

  - ``list_role_assignments_for_project`` — every user with a project-scoped
    role on this project, grouped by role (carries assignment ids for
    revocation). Still reads the ``users.*`` mirror; the move to user-svc's
    role-assignment endpoint (which carries the ids) is a separate change.

  - ``list_assignable_users_for_project`` — union of (a) project-tier role
    holders, (b) all members of the project's vendor(s)/org(s), and (c) users
    in the project's divisions, minus admin/super_admin tier. The RBAC half
    now comes from user-svc's ``/authz/users`` (the single source of truth);
    this service only supplies its OWN resource facts — the project's vendor
    ids (``project.project_vendors``) and division codes (``project.projects``
    owner + ``project.activities`` concerned_divisions) — and unions locally.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import Role, User as MirrorUser, UserRoleAssignment
from app.models.activity import Activity
from app.models.project import Project
from app.models.project_vendor import ProjectVendor
from app.services.user_mgmt_client import UserMgmtClient


# Display priority when projecting a single "orgRole" from the set of roles
# a user holds (highest tier first).
_ORG_ROLE_PRIORITY = (
    "super_admin", "admin", "org_admin", "project_admin", "project_member",
)


def _highest_org_role(roles: List[str]) -> Optional[str]:
    held = set(roles or [])
    for tier in _ORG_ROLE_PRIORITY:
        if tier in held:
            return tier
    return None


class AssignableUsersRepository:
    def __init__(self, db: Session):
        self.db = db

    # ----- role assignments listing (still mirror-backed; needs ids) ---

    def list_role_assignments_for_project(
        self, project_id: str,
    ) -> List[Tuple[Any, Any, Any]]:
        """Return ``[(UserRoleAssignment, Role, User), ...]`` for users with
        a project-scoped grant on ``project_id``."""
        stmt = (
            select(UserRoleAssignment, Role, MirrorUser)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .join(MirrorUser, MirrorUser.id == UserRoleAssignment.user_id)
            .where(UserRoleAssignment.project_id == project_id)
            .where(MirrorUser.deleted_at.is_(None))
            .order_by(Role.name.asc(), MirrorUser.login.asc())
        )
        return [tuple(row) for row in self.db.execute(stmt).all()]

    # ----- local resource facts (this service owns these tables) -------

    def vendor_ids_for_project(self, project_id: str) -> List[str]:
        return list(self.db.execute(
            select(ProjectVendor.vendor_id)
            .where(ProjectVendor.project_id == project_id)
        ).scalars())

    def division_codes_for_project(self, project_id: str) -> Set[str]:
        """Owner division + the union of every live activity's
        concerned_divisions (Bug #173 — users added under a relevant
        division must surface in the picker)."""
        codes: Set[str] = set()
        owner_code = self.db.execute(
            select(Project.owner).where(Project.id == project_id)
        ).scalar_one_or_none()
        if owner_code:
            codes.add(owner_code)
        for (concerned,) in self.db.execute(
            select(Activity.concerned_divisions)
            .where(Activity.project_id == project_id)
            .where(Activity.deleted_at.is_(None))
        ).all():
            if concerned:
                for c in concerned:
                    if isinstance(c, str) and c:
                        codes.add(c)
        return codes

    # ----- assignable users picker (RBAC half from user-svc) -----------

    def list_assignable_users_for_project(
        self, project_id: str, *, authorization: str,
    ) -> List[Dict[str, Any]]:
        """Union of (a) project-role holders, (b) ALL members of the project's
        vendor(s)/org(s), and (c) users in the project's divisions —
        admin/super_admin tier excluded. The three RBAC queries are answered by
        user-svc's ``/authz/users``; this service supplies only the local
        resource facts.

        Bug #142: branch (b) is every user who belongs to a project's
        organization (home ``vendor_id``), not just that org's admins — any
        member of a mapped org must be assignable inside the project.

        Each entry carries ``id`` / ``login`` / ``email`` / ``full_name`` /
        ``org_role`` (highest tier the user holds).
        """
        vendor_ids = self.vendor_ids_for_project(project_id)
        division_codes = self.division_codes_for_project(project_id)

        client = UserMgmtClient()
        by_id: Dict[str, Dict[str, Any]] = {}

        def _merge(users: List[dict]) -> None:
            for u in users:
                uid = u.get("id")
                if uid and uid not in by_id:
                    by_id[uid] = u

        # (a) project-scoped role holders on this project.
        _merge(client.fetch_users(
            authorization=authorization,
            project_id=project_id,
            exclude_admin_tier=True,
        ))
        # (b) ALL members of the project's vendor(s)/org(s) — everyone whose
        # home organization is mapped to this project, not just org_admins
        # (Bug #142). admin/super_admin tier still excluded.
        if vendor_ids:
            _merge(client.fetch_users(
                authorization=authorization,
                vendor_ids=vendor_ids,
                exclude_admin_tier=True,
            ))
        # (c) users in the project's divisions.
        if division_codes:
            _merge(client.fetch_users(
                authorization=authorization,
                divisions=sorted(division_codes),
                exclude_admin_tier=True,
            ))

        out = [
            {
                "id": u.get("id"),
                "login": u.get("login"),
                "email": u.get("email"),
                "full_name": u.get("full_name"),
                "org_role": _highest_org_role(u.get("roles") or []),
            }
            for u in by_id.values()
        ]
        return sorted(out, key=lambda x: (x["login"] or ""))
