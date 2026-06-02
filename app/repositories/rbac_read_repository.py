"""Cross-schema READ-ONLY repository for the users.* RBAC tables.

Used by middleware/auth_middleware.py on every authed request to:
  1. Check if the JWT's jti is in users.revoked_tokens.
  2. Hydrate user_permissions (flat union, role-derived + direct grants).
  3. Hydrate scoped_permissions (Doc-41 Dict[(kind, id), Set[str]]).
  4. Check is_admin via the seeded `admin` / `super_admin` role.

NEVER writes to users.* — that's user-svc's job. Project-svc reads only.
"""
from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    RevokedToken,
    Role,
    RolePermission,
    UserPermission,
    UserRole,
    UserRoleAssignment,
)


_ADMIN_ROLE_NAMES = ("admin", "super_admin")


class RbacReadRepository:
    def __init__(self, db: Session):
        self.db = db

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        return self.db.get(RevokedToken, jti) is not None

    def effective_permissions_for_user(self, user_id: str) -> Set[str]:
        """Flat union of role-derived + direct-grant codes."""
        if not user_id:
            return set()

        perms: Set[str] = set()

        # Legacy global tier (users.user_roles)
        stmt_legacy = (
            select(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_legacy).all():
            perms.add(code)

        # Doc-41 scoped tier (users.user_role_assignments)
        stmt_scoped = (
            select(RolePermission.permission_code)
            .join(
                UserRoleAssignment,
                UserRoleAssignment.role_id == RolePermission.role_id,
            )
            .where(UserRoleAssignment.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_scoped).all():
            perms.add(code)

        # Direct grants (users.user_permissions)
        stmt_direct = select(UserPermission.permission_code).where(
            UserPermission.user_id == user_id
        )
        for (code,) in self.db.execute(stmt_direct).all():
            perms.add(code)

        return perms

    def _add_legacy_global_tier(
        self,
        user_id: str,
        scoped: Dict[Tuple[str, Optional[str]], Set[str]],
    ) -> None:
        """Legacy global tier → ('global', None). UserRole + RolePermission."""
        legacy_codes: Set[str] = set()
        stmt_legacy = (
            select(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        for (code,) in self.db.execute(stmt_legacy).all():
            legacy_codes.add(code)
        if legacy_codes:
            scoped[("global", None)] = legacy_codes

    def _add_doc41_scoped_tier(
        self,
        user_id: str,
        scoped: Dict[Tuple[str, Optional[str]], Set[str]],
    ) -> Set[str]:
        """Doc-41 scoped tier (project / org / global). Returns the set of
        org_ids touched, used downstream by the vendor->project projection."""
        org_ids_seen: Set[str] = set()
        stmt_scoped = (
            select(
                RolePermission.permission_code,
                UserRoleAssignment.organization_id,
                UserRoleAssignment.project_id,
            )
            .join(
                UserRoleAssignment,
                UserRoleAssignment.role_id == RolePermission.role_id,
            )
            .where(UserRoleAssignment.user_id == user_id)
        )
        for code, org_id, project_id in self.db.execute(stmt_scoped).all():
            if project_id is not None:
                key: Tuple[str, Optional[str]] = ("project", project_id)
            elif org_id is not None:
                key = ("org", org_id)
                org_ids_seen.add(org_id)
            else:
                key = ("global", None)
            scoped.setdefault(key, set()).add(code)
        return org_ids_seen

    def _add_direct_grants(
        self,
        user_id: str,
        scoped: Dict[Tuple[str, Optional[str]], Set[str]],
    ) -> None:
        """Direct user_permissions rows → treated as global tier."""
        direct_codes: Set[str] = set()
        stmt_direct = select(UserPermission.permission_code).where(
            UserPermission.user_id == user_id
        )
        for (code,) in self.db.execute(stmt_direct).all():
            direct_codes.add(code)
        if direct_codes:
            scoped.setdefault(("global", None), set()).update(direct_codes)

    def _project_vendor_perms_onto_projects(
        self,
        scoped: Dict[Tuple[str, Optional[str]], Set[str]],
        org_ids_seen: Set[str],
    ) -> None:
        """Round-7 VENDOR->PROJECT projection: for every ('org', V) key,
        replicate its permission set onto ('project', P) for every P in
        ``project.project_vendors`` mapped to V. project-svc OWNS the
        project_vendors table — query directly, not via a cross-schema
        mirror."""
        if not org_ids_seen:
            return
        from app.models.project_vendor import ProjectVendor

        stmt = (
            select(ProjectVendor.vendor_id, ProjectVendor.project_id)
            .where(ProjectVendor.vendor_id.in_(org_ids_seen))
        )
        for vid, pid in self.db.execute(stmt).all():
            org_perms = scoped.get(("org", vid), set())
            if not org_perms:
                continue
            scoped.setdefault(("project", pid), set()).update(org_perms)

    def effective_permissions_by_scope(
        self, user_id: str,
    ) -> Dict[Tuple[str, Optional[str]], Set[str]]:
        """Doc-41 scoped permission map.

        Returns ``{(kind, scope_id): set(codes)}`` where ``kind`` is one of
        ``'global' | 'org' | 'project'`` and ``scope_id`` is the vendor_id
        or project_id (None for global).

        Round-7 addition — VENDOR->PROJECT PROJECTION:
          For every ("org", V) key, project those permissions onto
          ("project", P) for every P in project.project_vendors mapped to V.
          Source of truth is the role-assignment row's organization_id;
          users.users.vendor_id is NOT consulted.

        Tier-merge order preserved (legacy → scoped → direct → projection)
        so the final map for any input is identical to the legacy in-line
        form.
        """
        scoped: Dict[Tuple[str, Optional[str]], Set[str]] = {}
        if not user_id:
            return scoped

        self._add_legacy_global_tier(user_id, scoped)
        org_ids_seen = self._add_doc41_scoped_tier(user_id, scoped)
        self._add_direct_grants(user_id, scoped)
        self._project_vendor_perms_onto_projects(scoped, org_ids_seen)

        return scoped

    def is_admin(self, user_id: str) -> bool:
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

        stmt_scoped = (
            select(Role.id)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(Role.name.in_(_ADMIN_ROLE_NAMES))
            .limit(1)
        )
        if self.db.execute(stmt_scoped).first():
            return True

        return False
