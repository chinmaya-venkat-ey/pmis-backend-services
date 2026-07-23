"""RbacRepository — canonical authoritative RBAC read+write surface.

user-svc OWNS the RBAC tables; this repository is the only place that
INSERTs/DELETEs rows into:
  - users.permissions
  - users.roles
  - users.role_permissions
  - users.user_permissions
  - users.user_role_assignments  (the legacy `user_roles` table is
    read-only for migration purposes and is not written here)

Other services hold read-only mirrors (via _cross_schema.py) and use a
narrower `RbacReadRepository` that only exposes the read methods.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from app.core.permissions import ADMIN_ROLE, SUPER_ADMIN_ROLE
from app.models.permission import Permission
from app.models.revoked_token import RevokedToken
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.user_role import UserRole
from app.models.user_role_assignment import UserRoleAssignment


_ADMIN_ROLE_NAMES = (ADMIN_ROLE, SUPER_ADMIN_ROLE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RbacRepository:
    """Authoritative reads + writes for users.* RBAC tables."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ permissions catalog

    def get_permission(self, code: str) -> Optional[Permission]:
        return self.db.get(Permission, code)

    def create_permission(
        self,
        *,
        code: str,
        name: str,
        description: Optional[str] = None,
        is_builtin: bool = False,
    ) -> Permission:
        row = Permission(code=code, name=name, description=description, is_builtin=is_builtin)
        self.db.add(row)
        self.db.flush()
        return row

    def list_permissions(self) -> List[Permission]:
        return list(self.db.execute(select(Permission).order_by(Permission.code.asc())).scalars().all())

    def update_permission(
        self,
        row: Permission,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Permission:
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        self.db.flush()
        return row

    def delete_permission(self, code: str) -> int:
        row = self.get_permission(code)
        if row is None:
            return 0
        self.db.delete(row)
        self.db.flush()
        return 1

    # ------------------------------------------------------------------ roles

    def get_role(self, role_id: int) -> Optional[Role]:
        return self.db.get(Role, role_id)

    def get_role_by_name(self, name: str) -> Optional[Role]:
        return self.db.execute(select(Role).where(Role.name == name)).scalars().first()

    def list_roles(self) -> List[Role]:
        return list(self.db.execute(select(Role).order_by(Role.name.asc())).scalars().all())

    def create_role(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        builtin: bool = False,
    ) -> Role:
        row = Role(name=name, description=description, builtin=builtin)
        self.db.add(row)
        self.db.flush()
        return row

    def update_role(
        self,
        row: Role,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Role:
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        self.db.flush()
        return row

    def delete_role(self, role_id: int) -> int:
        row = self.get_role(role_id)
        if row is None:
            return 0
        # Cascade via app: delete role_permissions, then assignments, then role.
        self.db.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        self.db.execute(
            delete(UserRoleAssignment).where(UserRoleAssignment.role_id == role_id)
        )
        self.db.execute(
            delete(UserRole).where(UserRole.role_id == role_id)
        )
        self.db.delete(row)
        self.db.flush()
        return 1

    # ------------------------------------------------------------------ role ↔ permission grants

    def list_role_permissions(self, role_id: int) -> List[str]:
        stmt = (
            select(RolePermission.permission_code)
            .where(RolePermission.role_id == role_id)
            .order_by(RolePermission.permission_code.asc())
        )
        return [row[0] for row in self.db.execute(stmt).all()]

    def grant_permissions_to_role(
        self, role_id: int, permission_codes: Iterable[str],
    ) -> int:
        """Bulk insert. Skips codes already granted. Returns # added."""
        existing = set(self.list_role_permissions(role_id))
        added = 0
        for code in permission_codes:
            if code in existing:
                continue
            self.db.add(RolePermission(role_id=role_id, permission_code=code))
            added += 1
        if added:
            self.db.flush()
        return added

    def revoke_permission_from_role(self, role_id: int, permission_code: str) -> int:
        result = self.db.execute(
            delete(RolePermission)
            .where(RolePermission.role_id == role_id)
            .where(RolePermission.permission_code == permission_code)
        )
        self.db.flush()
        return result.rowcount or 0

    def replace_role_permissions(
        self, role_id: int, permission_codes: Iterable[str],
    ) -> Tuple[int, int]:
        """Replace the set of permissions for a role atomically.
        Returns (added, removed)."""
        new_set = set(permission_codes)
        current = set(self.list_role_permissions(role_id))
        to_add = new_set - current
        to_remove = current - new_set
        for code in to_add:
            self.db.add(RolePermission(role_id=role_id, permission_code=code))
        if to_remove:
            self.db.execute(
                delete(RolePermission)
                .where(RolePermission.role_id == role_id)
                .where(RolePermission.permission_code.in_(to_remove))
            )
        self.db.flush()
        return len(to_add), len(to_remove)

    # ------------------------------------------------------------------ user ↔ permission direct grants

    def list_user_permissions(self, user_id: str) -> List[str]:
        stmt = (
            select(UserPermission.permission_code)
            .where(UserPermission.user_id == user_id)
            .order_by(UserPermission.permission_code.asc())
        )
        return [row[0] for row in self.db.execute(stmt).all()]

    def grant_permission_to_user(
        self, user_id: str, permission_code: str, *, granted_by_user_id: Optional[str] = None,
    ) -> bool:
        """Idempotent: returns True if newly added, False if already present."""
        existing = self.db.get(UserPermission, (user_id, permission_code))
        if existing is not None:
            return False
        self.db.add(
            UserPermission(
                user_id=user_id,
                permission_code=permission_code,
                created_by=granted_by_user_id,
            )
        )
        self.db.flush()
        return True

    def revoke_permission_from_user(
        self, user_id: str, permission_code: str,
    ) -> int:
        result = self.db.execute(
            delete(UserPermission)
            .where(UserPermission.user_id == user_id)
            .where(UserPermission.permission_code == permission_code)
        )
        self.db.flush()
        return result.rowcount or 0

    # ------------------------------------------------------------------ effective permission queries

    def _project_base_reads(self, user_id: str) -> Set[str]:
        """Curated cross-cutting reads surfaced at GLOBAL scope when the user's
        ``org_role`` column is a project role (``PROJECT_ROLE_BASE_CODES``).

        project_admin / project_member fuse capability WITH project scope, so a
        holder with NO project would otherwise hold these reads nowhere. The
        no-project case is only reachable via user create/update (which sets the
        column); team-management assignment always names a project. ADDITIVE and
        read-only — no project-nature code is included, so nothing leaks into the
        global tier and ``require_project_permission`` still gates per project.
        """
        from app.core.permissions import (
            PROJECT_ONLY_ROLE_NAMES,
            PROJECT_ROLE_BASE_CODES,
        )

        col = self.db.execute(
            select(User.org_role).where(User.id == user_id)
        ).scalar()
        if (col or "").strip().lower() in PROJECT_ONLY_ROLE_NAMES:
            return set(PROJECT_ROLE_BASE_CODES)
        return set()

    def effective_permissions_for_user(self, user_id: str) -> Set[str]:
        """Flat union of GLOBAL role-derived + direct-grant codes.

        §3.3 (2026-06-02 audit): the flat ``user_permissions`` set is what
        ``require_permission`` reads. To keep project-scoped grants from
        bleeding into global ``require_permission`` checks, only codes from
        GLOBAL-scope grants enter this set.

        Exception: admin and super_admin are tier roles; their permissions
        are universal by design. An admin/super_admin assignment at ANY
        scope contributes its codes to the flat set. (Runtime APIs reject
        scoped admin/super_admin assignments, but legacy data could exist.)
        Scoped grants from OTHER (non-admin-tier) roles are accessible only
        via ``effective_permissions_by_scope`` / scoped checks.
        """
        if not user_id:
            return set()
        perms: Set[str] = set()

        # Legacy global tier (users.user_roles → role_permissions). The
        # user_roles table is global-by-design — every grant here is global.
        stmt = (
            select(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt).all():
            perms.add(code)

        # Doc-41 scoped tier (users.user_role_assignments → role_permissions).
        # Include codes from GLOBAL-scope assignments (org_id IS NULL AND
        # project_id IS NULL) OR from any-scope admin/super_admin assignment
        # (admin tier is universal — see §3.3 docstring above).
        stmt = (
            select(RolePermission.permission_code)
            .join(
                UserRoleAssignment,
                UserRoleAssignment.role_id == RolePermission.role_id,
            )
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(
                or_(
                    and_(
                        UserRoleAssignment.organization_id.is_(None),
                        UserRoleAssignment.project_id.is_(None),
                    ),
                    Role.name.in_(_ADMIN_ROLE_NAMES),
                )
            )
        )
        for (code,) in self.db.execute(stmt).all():
            perms.add(code)

        # Direct user grants (always global — user_permissions has no scope).
        for code in self.list_user_permissions(user_id):
            perms.add(code)

        # project_role_base: cross-cutting reads for a project_admin/member whose
        # role is otherwise project-scoped (so a no-project holder still has them).
        perms |= self._project_base_reads(user_id)

        return perms

    def effective_permissions_by_scope(
        self, user_id: str,
    ) -> Dict[Tuple[str, Optional[str]], Set[str]]:
        """Returns a Dict where key is (kind, id) and value is the set of
        permission codes the user holds at that scope:

          ("global", None) → perms from user_roles (global tier) + user_permissions
          ("org", <vendor_id>) → perms from user_role_assignments with org scope
          ("project", <project_id>) → perms from user_role_assignments with project scope

        require_project_permission / require_org_permission consult this map.
        Global codes apply to every scope (admin shortcut).

        Round-7 addition — VENDOR->PROJECT PROJECTION:
          For every (caller, role) at scope ("org", V), project the role's
          permissions onto ("project", P) for every P in
          masters.vendors V's project_vendors mapping. This implements
          "org_admin on vendor V is implicitly org_admin on every project
          mapped to V" without needing a separate project assignment row.

          The same projection runs for the caller's OWN vendor_id (from
          users.users.vendor_id) when the caller holds an org-tier role at
          GLOBAL scope — common pattern for vendor-affiliated users.

        ROLE-AGNOSTIC PROJECTION (current): the projection fires for any
        vendor-scoped grant, regardless of role name. After r014 the only
        roles that can sit at vendor scope are org_admin (and any future
        role explicitly seeded vendor-allowed); PA / PM are blocked here
        and are project-scoped only.

        FUTURE — OPTION 3 (data-driven projection toggle):
          Add a ``vendor_projection BOOL DEFAULT FALSE`` column to
          ``users.roles``; flip it to TRUE in the seed for org_admin (and
          any future role that should project onto vendor projects). This
          method + ``list_projects_for_user`` then add
          ``Role.vendor_projection IS TRUE`` to their org-scope JOINs.
          Detailed migration / refactor checklist lives in the local
          design note at
          ``<PMIS-root>/role-vendor-projection-option3.md`` (not in any
          git repo — design-track only). Mirror the change in
          ``UserRoleAssignmentRepository.list_projects_for_user`` (the
          (b) source) so the listing stays symmetric with this method.
        """
        if not user_id:
            return {}
        out: Dict[Tuple[str, Optional[str]], Set[str]] = {}

        # Global tier — user_roles + user_permissions
        global_perms: Set[str] = set()
        stmt = (
            select(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt).all():
            global_perms.add(code)
        for code in self.list_user_permissions(user_id):
            global_perms.add(code)
        # project_role_base: same curated global reads as the flat set, so
        # /authz/context's `scoped.global` stays consistent with `permissions`.
        global_perms |= self._project_base_reads(user_id)
        if global_perms:
            out[("global", None)] = global_perms

        # Scoped tier — group by (org_id, project_id) per assignment row.
        # §3.3 (2026-06-02 audit): admin/super_admin tier roles are
        # universal — their codes always land in ("global", None), even if
        # the assignment row carries a scope. (Runtime APIs reject scoped
        # admin/super_admin assignments, but legacy data could exist.)
        org_ids_seen: Set[str] = set()
        stmt = (
            select(
                UserRoleAssignment.organization_id,
                UserRoleAssignment.project_id,
                Role.name,
                RolePermission.permission_code,
            )
            .join(
                RolePermission,
                RolePermission.role_id == UserRoleAssignment.role_id,
            )
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id == user_id)
        )
        for org_id, project_id, role_name, code in self.db.execute(stmt).all():
            if role_name in _ADMIN_ROLE_NAMES:
                # Universal-tier role — always global, regardless of row scope.
                key: Tuple[str, Optional[str]] = ("global", None)
            elif org_id is None and project_id is None:
                key = ("global", None)
            elif org_id is not None:
                key = ("org", org_id)
                org_ids_seen.add(org_id)
            else:
                key = ("project", project_id)
            out.setdefault(key, set()).add(code)

        # Round-7: vendor->project projection.
        # For every ("org", vendor_id) key, project those permissions onto
        # every ("project", project_id) for projects mapped to that vendor
        # via project.project_vendors. This implements "org_admin assigned
        # to vendor V has implicit org_admin authority on every project
        # mapped to V" without a separate project-tier assignment per project.
        #
        # The user's `users.vendor_id` field (their employer) is NOT used
        # here — projection sources ONLY from explicit role-assignment rows
        # at org scope. A user can be employed by V (vendor_id=V) without
        # holding any org-tier role on V, and conversely a user can hold
        # org_admin on V without being employed there. The role-assignment
        # row is the single source of truth.
        if org_ids_seen:
            from app.models._cross_schema import ProjectVendor, Vendor

            # #246: project ONLY through vendors that are still live. Deleting a
            # vendor (org) soft-deletes masters.vendors but PRESERVES the
            # project_vendors mapping rows, so without this join an org_admin on
            # a removed vendor keeps implicit ("project", pid) scope and the
            # project lingers in their list showing "no organization". Joining to
            # the vendor + filtering deleted_at drops those dangling references.
            stmt = (
                select(ProjectVendor.vendor_id, ProjectVendor.project_id)
                .join(Vendor, Vendor.id == ProjectVendor.vendor_id)
                .where(
                    ProjectVendor.vendor_id.in_(org_ids_seen),
                    Vendor.deleted_at.is_(None),
                )
            )
            for vid, pid in self.db.execute(stmt).all():
                org_perms = out.get(("org", vid), set())
                if not org_perms:
                    continue
                out.setdefault(("project", pid), set()).update(org_perms)

        return out

    def _project_role_ids_by_name(self) -> Dict[str, int]:
        """{name: id} for the builtin project roles (project_admin/member)."""
        from app.core.permissions import PROJECT_ONLY_ROLE_NAMES

        return dict(self.db.execute(
            select(Role.name, Role.id)
            .where(Role.name.in_(PROJECT_ONLY_ROLE_NAMES))
            .where(Role.builtin.is_(True))
        ).all())

    @staticmethod
    def _column_role_fallback_entry(
        org_role_col: Optional[str],
        existing: List[Dict[str, Optional[object]]],
        role_ids: Dict[str, int],
    ) -> Optional[Dict[str, Optional[object]]]:
        """Synthetic orgRole entry derived from the ``users.org_role`` COLUMN.

        project_admin / project_member fuse capability with project scope, so a
        holder with NO project has no assignment row — the row-derived orgRole
        list above would then be empty and the user would display with no role
        even though the column designates them a project_admin/member. Surface
        that designation here so the user-facing orgRole reflects it (the FE
        relies on orgRole for display). Returns the entry or None.

        Fires ONLY when the column is a project role AND no assignment-derived
        entry for that role already exists — so a holder WITH projects (who has
        project-scoped entries) is untouched and never duplicated. ``scope`` is
        "global" (an existing FE-handled value), mirroring where the resolver
        surfaces this user's active capabilities (the global cross-cutting
        reads); ``assignment_id`` is None — there is no row to revoke.
        """
        from app.core.permissions import PROJECT_ONLY_ROLE_NAMES

        col = (org_role_col or "").strip().lower()
        if col not in PROJECT_ONLY_ROLE_NAMES or col not in role_ids:
            return None
        if any(e["role_name"] == col for e in existing):
            return None
        return {
            "role_name": col,
            "role_id": role_ids[col],
            "scope": "global",
            "organization_id": None,
            "project_id": None,
            "project_code": None,
            "assignment_id": None,
            "created_at": None,
            "created_by": None,
        }

    def builtin_role_assignments_for_user(self, user_id: str) -> List[Dict[str, Optional[object]]]:
        """Return every BUILTIN role assignment the user currently holds,
        across both legacy ``user_roles`` and scoped ``user_role_assignments``.

        2026-06-02: single source of truth for the user-facing ``orgRole``
        field. Replaces the prior hand-maintained ``ORG_TIER_ROLES`` tuple
        — ``Role.builtin = True`` filtering means any future builtin role
        (created via migration) appears automatically. Non-builtin custom
        roles such as ``test_role`` are excluded.

        Each returned dict has the shape::

            {
              "role_name":       str,
              "role_id":         int,
              "scope":           "global" | "org" | "project",
              "organization_id": Optional[str],
              "project_id":      Optional[str],
              "project_code":    Optional[str],   # resolved for project scope
              "assignment_id":   Optional[int],   # None for legacy user_roles
              "created_at":      Optional[datetime],
              "created_by":      Optional[str],
            }

        Duplicates across the two tier-tables are collapsed by
        (role_name, scope, organization_id, project_id) — the SCOPED row
        (user_role_assignments) wins because it carries a surrogate
        ``assignment_id`` the FE may need for revocation. Output is
        sorted for deterministic FE rendering.
        """
        if not user_id:
            return []

        out: List[Dict[str, Optional[object]]] = []
        seen: set = set()

        # Process the Doc-41 scoped tier FIRST so it wins on (role,scope,
        # org_id,project_id) collisions — those rows carry assignment_id
        # which the FE needs for revocation.
        scoped_rows = self.db.execute(
            select(
                Role.name,
                Role.id,
                UserRoleAssignment.organization_id,
                UserRoleAssignment.project_id,
                UserRoleAssignment.id,
                UserRoleAssignment.created_at,
                UserRoleAssignment.created_by,
            )
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Role.builtin.is_(True))
        ).all()
        for role_name, role_id, org_id, project_id, ass_id, created_at, created_by in scoped_rows:
            if org_id is None and project_id is None:
                scope = "global"
            elif org_id is not None:
                scope = "org"
            else:
                scope = "project"
            key = (role_name, scope, org_id, project_id)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "role_name": role_name,
                "role_id": role_id,
                "scope": scope,
                "organization_id": org_id,
                "project_id": project_id,
                "project_code": None,  # filled below for project-scoped rows
                "assignment_id": ass_id,
                "created_at": created_at,
                "created_by": created_by,
            })

        # Legacy global tier (users.user_roles is global-by-design; no
        # surrogate id since the PK is composite (user_id, role_id)).
        for role_name, role_id, created_at, created_by in self.db.execute(
            select(Role.name, Role.id, UserRole.created_at, UserRole.created_by)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Role.builtin.is_(True))
        ).all():
            key = (role_name, "global", None, None)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "role_name": role_name,
                "role_id": role_id,
                "scope": "global",
                "organization_id": None,
                "project_id": None,
                "project_code": None,
                "assignment_id": None,  # legacy table has no surrogate id
                "created_at": created_at,
                "created_by": created_by,
            })

        # Resolve project_code for every project-scoped row in one batch
        # query against the cross-schema Project mirror (avoid N+1).
        project_ids = {
            o["project_id"] for o in out
            if o["scope"] == "project" and o["project_id"]
        }
        if project_ids:
            from app.models._cross_schema import Project as ProjectMirror
            code_by_id = dict(self.db.execute(
                select(ProjectMirror.id, ProjectMirror.project_code)
                .where(ProjectMirror.id.in_(project_ids))
            ).all())
            for entry in out:
                if entry["scope"] == "project" and entry["project_id"]:
                    entry["project_code"] = code_by_id.get(entry["project_id"])

        # Fallback: a no-project project_admin/member designated only via the
        # org_role column has no assignment row — surface it so orgRole reflects
        # the role (FE display).
        col = self.db.execute(
            select(User.org_role).where(User.id == user_id)
        ).scalar()
        entry = self._column_role_fallback_entry(col, out, self._project_role_ids_by_name())
        if entry is not None:
            out.append(entry)

        out.sort(key=lambda e: (
            e["role_name"], e["scope"],
            e["organization_id"] or "", e["project_id"] or "",
        ))
        return out

    def user_has_admin_role(self, user_id: str) -> bool:
        """True if the user holds `admin` or `super_admin` GLOBALLY.

        Round-8 C5 fix: when reading from `user_role_assignments`, require
        BOTH `organization_id IS NULL` AND `project_id IS NULL`. A scoped
        admin/super_admin assignment must NOT make the user globally admin
        (otherwise an admin caller could mint a "project-scoped admin" via
        the role-assignment API and have the victim register as global
        admin in the middleware).

        Legacy `users.user_roles` is global-by-design — no scope filter
        needed there.
        """
        if not user_id:
            return False

        stmt_legacy = (
            select(Role.id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .limit(1)
        )
        if self.db.execute(stmt_legacy).first():
            return True

        # Round-8 C5: scope-restrict the user_role_assignments lookup to
        # GLOBAL assignments only. A project-scoped or org-scoped admin
        # assignment must not yield is_admin=True at the middleware.
        stmt_scoped = (
            select(Role.id)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .where(UserRoleAssignment.organization_id.is_(None))
            .where(UserRoleAssignment.project_id.is_(None))
            .limit(1)
        )
        return self.db.execute(stmt_scoped).first() is not None

    # ------------------------------------------------------------------ batched (per-page) variants for the user LIST (kill the N+1)

    def builtin_role_assignments_for_users(
        self, user_ids: List[str],
    ) -> Dict[str, List[Dict[str, Optional[object]]]]:
        """Per-page batch of :meth:`builtin_role_assignments_for_user`.

        One scoped query + one legacy query for ALL ``user_ids``, one
        project_code resolution, grouped by user_id. Each user's list is
        deduped and sorted identically to the single-user method, so the list
        response matches the detail response exactly.
        """
        out: Dict[str, List[Dict[str, Optional[object]]]] = {uid: [] for uid in user_ids}
        if not user_ids:
            return out
        seen: Dict[str, set] = {uid: set() for uid in user_ids}

        # scoped tier FIRST (wins on collisions; carries assignment_id)
        for uid, role_name, role_id, org_id, project_id, ass_id, created_at, created_by in self.db.execute(
            select(
                UserRoleAssignment.user_id,
                Role.name, Role.id,
                UserRoleAssignment.organization_id, UserRoleAssignment.project_id,
                UserRoleAssignment.id, UserRoleAssignment.created_at, UserRoleAssignment.created_by,
            )
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id.in_(user_ids))
            .where(Role.builtin.is_(True))
        ).all():
            if org_id is None and project_id is None:
                scope = "global"
            elif org_id is not None:
                scope = "org"
            else:
                scope = "project"
            key = (role_name, scope, org_id, project_id)
            if key in seen[uid]:
                continue
            seen[uid].add(key)
            out[uid].append({
                "role_name": role_name, "role_id": role_id, "scope": scope,
                "organization_id": org_id, "project_id": project_id,
                "project_code": None, "assignment_id": ass_id,
                "created_at": created_at, "created_by": created_by,
            })

        # legacy global tier
        for uid, role_name, role_id, created_at, created_by in self.db.execute(
            select(UserRole.user_id, Role.name, Role.id, UserRole.created_at, UserRole.created_by)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id.in_(user_ids))
            .where(Role.builtin.is_(True))
        ).all():
            key = (role_name, "global", None, None)
            if key in seen[uid]:
                continue
            seen[uid].add(key)
            out[uid].append({
                "role_name": role_name, "role_id": role_id, "scope": "global",
                "organization_id": None, "project_id": None, "project_code": None,
                "assignment_id": None, "created_at": created_at, "created_by": created_by,
            })

        # resolve project_code for every project-scoped row in ONE query
        project_ids = {
            o["project_id"] for lst in out.values() for o in lst
            if o["scope"] == "project" and o["project_id"]
        }
        if project_ids:
            from app.models._cross_schema import Project as ProjectMirror
            code_by_id = dict(self.db.execute(
                select(ProjectMirror.id, ProjectMirror.project_code)
                .where(ProjectMirror.id.in_(project_ids))
            ).all())
            for lst in out.values():
                for entry in lst:
                    if entry["scope"] == "project" and entry["project_id"]:
                        entry["project_code"] = code_by_id.get(entry["project_id"])

        # Fallback (same as the single-user method): surface a no-project
        # project_admin/member from the org_role column so orgRole is non-empty.
        role_ids = self._project_role_ids_by_name()
        cols = dict(self.db.execute(
            select(User.id, User.org_role).where(User.id.in_(user_ids))
        ).all())
        for uid in user_ids:
            entry = self._column_role_fallback_entry(cols.get(uid), out[uid], role_ids)
            if entry is not None:
                out[uid].append(entry)

        for lst in out.values():
            lst.sort(key=lambda e: (
                e["role_name"], e["scope"],
                e["organization_id"] or "", e["project_id"] or "",
            ))
        return out

    def users_with_admin_role(self, user_ids: List[str]) -> set:
        """Subset of ``user_ids`` holding admin/super_admin GLOBALLY — batched
        :meth:`user_has_admin_role` (legacy any-scope; scoped global-only)."""
        result: set = set()
        if not user_ids:
            return result
        for (uid,) in self.db.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
        ).all():
            result.add(uid)
        for (uid,) in self.db.execute(
            select(UserRoleAssignment.user_id)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id.in_(user_ids))
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .where(UserRoleAssignment.organization_id.is_(None))
            .where(UserRoleAssignment.project_id.is_(None))
        ).all():
            result.add(uid)
        return result

    def super_admin_user_ids(self, user_ids: List[str]) -> set:
        """Subset of ``user_ids`` holding super_admin via either tier (any
        scope) — batched of the controller's ``_is_super_admin``."""
        from app.core.permissions import SUPER_ADMIN_ROLE
        result: set = set()
        if not user_ids:
            return result
        role = self.get_role_by_name(SUPER_ADMIN_ROLE)
        if role is None:
            return result
        for (uid,) in self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.user_id.in_(user_ids))
            .where(UserRole.role_id == role.id)
        ).all():
            result.add(uid)
        for (uid,) in self.db.execute(
            select(UserRoleAssignment.user_id)
            .where(UserRoleAssignment.user_id.in_(user_ids))
            .where(UserRoleAssignment.role_id == role.id)
        ).all():
            result.add(uid)
        return result

    # ------------------------------------------------------------------ revoked tokens

    def is_revoked(self, jti: str) -> bool:
        """O(1) PK lookup."""
        if not jti:
            return False
        return self.db.get(RevokedToken, jti) is not None

    # §3.4.2 (2026-06-02 audit): list/assign/unassign_user_legacy_role
    # removed. They bypassed _assert_caller_can_grant. user_roles is now
    # write-only by migration (bootstrap superadmin seed); the runtime
    # surface lives on user_role_assignments via RoleAssignmentService.
