"""Repository for the DB-driven RBAC tables (doc 21 part B + doc 41 scope).

Single class managing CRUD on permissions, role-permission grants,
user-role assignments, and direct user-permission grants. Centralizes
both the read (effective permissions for a user) and write paths so the
rest of the codebase doesn't reach into individual model classes.

Doc 41 added scoped role assignments via ``user_role_assignments``
(org / project scope). The legacy ``user_roles`` and
``project_members.roles[]`` paths stay live during the migration
window; the union returned by ``effective_permissions_for_user``
now includes scoped grants too, so old call sites keep working.

All writes flush but do NOT commit — caller owns the transaction.
"""
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, delete, exists, func, or_
from sqlalchemy.orm import Session

from ....core.permissions import (
    ADMIN_ROLE_NAME,
    VENDOR_ROLE_NAME,
    VENDOR_ROLE_PERMISSIONS,
    ADMIN_ROLE_PERMISSIONS,
    BUILTIN_PERMISSIONS,
    MEMBER_ROLE_NAME,
    MEMBER_ROLE_PERMISSIONS,
    VIEWER_ROLE_NAME,
    VIEWER_ROLE_PERMISSIONS,
    # Doc 41 — scoped roles + their seeded permission sets.
    SUPER_ADMIN_ROLE_NAME,
    SUPER_ADMIN_ROLE_PERMISSIONS,
    ADMIN_FULL_ROLE_PERMISSIONS,
    ORG_ADMIN_ROLE_NAME,
    ORG_ADMIN_ROLE_PERMISSIONS,
    PROJECT_ADMIN_ROLE_NAME,
    PROJECT_ADMIN_ROLE_PERMISSIONS,
    PROJECT_MEMBER_ROLE_NAME,
    PROJECT_MEMBER_ROLE_PERMISSIONS,
    DIVISION_MEMBER_ROLE_NAME,
    DIVISION_MEMBER_ROLE_PERMISSIONS,
)
from ..models.permission import PermissionModel
from ..models.role import RoleModel
from ..models.role_permission import RolePermissionModel
from ..models.user_permission import UserPermissionModel
from ..models.user_role import UserRoleModel
from ..models.user_role_assignment import UserRoleAssignmentModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RbacRepository:
    def __init__(self, db: Session):
        self.db = db

    # -------------------------------------------------------------------
    # Effective permissions for a user
    # -------------------------------------------------------------------

    def effective_permissions_for_user(self, user_id: str) -> Set[str]:
        """Union of role-derived (legacy + scoped) and direct grants.

        Doc 41: the union now includes scoped role assignments
        (``user_role_assignments``) too — across every scope. Callers
        that need a per-scope view should use
        :meth:`effective_permissions_by_scope` instead.
        """
        if user_id is None:
            return set()
        # Legacy global role grants (user_roles).
        legacy_role_codes = {
            r[0]
            for r in self.db.query(RolePermissionModel.permission_code)
            .join(UserRoleModel, UserRoleModel.role_id == RolePermissionModel.role_id)
            .filter(UserRoleModel.user_id == user_id)
            .all()
        }
        # Doc 41 scoped role assignments (org / project / global).
        scoped_role_codes = {
            r[0]
            for r in self.db.query(RolePermissionModel.permission_code)
            .join(
                UserRoleAssignmentModel,
                UserRoleAssignmentModel.role_id == RolePermissionModel.role_id,
            )
            .filter(UserRoleAssignmentModel.user_id == user_id)
            .all()
        }
        direct_codes = {
            r[0]
            for r in self.db.query(UserPermissionModel.permission_code)
            .filter(UserPermissionModel.user_id == user_id)
            .all()
        }
        return legacy_role_codes | scoped_role_codes | direct_codes

    # -------------------------------------------------------------------
    # Doc 41 — per-scope permission view
    # -------------------------------------------------------------------

    def effective_permissions_by_scope(
        self, user_id: str,
    ) -> Dict[Tuple[str, Optional[str]], Set[str]]:
        """Return permissions grouped by scope key.

        Output shape::

            {
                ("global", None):           {<perm code>, ...},
                ("org", "<vendor_id>"):     {<perm code>, ...},
                ("project", "<project_id>"): {<perm code>, ...},
            }

        Includes:
          * Legacy ``user_roles`` rows — accumulated under ``("global", None)``.
          * Direct ``user_permissions`` grants — also under ``("global", None)``.
          * Scoped ``user_role_assignments`` — bucketed by their scope.

        Used by the scope-aware route helpers
        (``require_project_permission``, ``require_org_permission``).
        Empty dict for unauthenticated callers.
        """
        out: Dict[Tuple[str, Optional[str]], Set[str]] = {}
        if user_id is None:
            return out

        # Legacy global (user_roles → role_permissions).
        legacy = (
            self.db.query(RolePermissionModel.permission_code)
            .join(UserRoleModel, UserRoleModel.role_id == RolePermissionModel.role_id)
            .filter(UserRoleModel.user_id == user_id)
            .all()
        )
        if legacy:
            out.setdefault(("global", None), set()).update(r[0] for r in legacy)

        # Direct grants → global.
        directs = (
            self.db.query(UserPermissionModel.permission_code)
            .filter(UserPermissionModel.user_id == user_id)
            .all()
        )
        if directs:
            out.setdefault(("global", None), set()).update(r[0] for r in directs)

        # Doc 41 scoped (user_role_assignments → role_permissions).
        scoped = (
            self.db.query(
                RolePermissionModel.permission_code,
                UserRoleAssignmentModel.organization_id,
                UserRoleAssignmentModel.project_id,
            )
            .join(
                UserRoleAssignmentModel,
                UserRoleAssignmentModel.role_id == RolePermissionModel.role_id,
            )
            .filter(UserRoleAssignmentModel.user_id == user_id)
            .all()
        )
        for code, org_id, project_id in scoped:
            if project_id is not None:
                key = ("project", project_id)
            elif org_id is not None:
                key = ("org", org_id)
            else:
                key = ("global", None)
            out.setdefault(key, set()).add(code)

        return out

    def user_has_admin_role(self, user_id: str) -> bool:
        """True iff the user holds admin or super_admin globally.

        Doc 41: also honours global rows in ``user_role_assignments``
        (scope is global when both org_id and project_id are NULL),
        and treats ``super_admin`` as admin for the legacy ``is_admin``
        flag — every code path that checked ``is_admin`` predates the
        admin/super_admin split.
        """
        if user_id is None:
            return False
        admin_names = (ADMIN_ROLE_NAME, SUPER_ADMIN_ROLE_NAME)
        # Legacy user_roles path.
        legacy = (
            self.db.query(
                exists().where(
                    and_(
                        UserRoleModel.user_id == user_id,
                        UserRoleModel.role_id == RoleModel.id,
                        RoleModel.name.in_(admin_names),
                    )
                )
            ).scalar()
            or False
        )
        if legacy:
            return True
        # Doc 41 scoped path — only global rows count for "is admin".
        scoped = (
            self.db.query(
                exists().where(
                    and_(
                        UserRoleAssignmentModel.user_id == user_id,
                        UserRoleAssignmentModel.role_id == RoleModel.id,
                        UserRoleAssignmentModel.organization_id.is_(None),
                        UserRoleAssignmentModel.project_id.is_(None),
                        RoleModel.name.in_(admin_names),
                    )
                )
            ).scalar()
            or False
        )
        return scoped

    def user_has_super_admin_role(self, user_id: str) -> bool:
        """True iff the user holds super_admin (legacy or scoped-global)."""
        if user_id is None:
            return False
        legacy = (
            self.db.query(
                exists().where(
                    and_(
                        UserRoleModel.user_id == user_id,
                        UserRoleModel.role_id == RoleModel.id,
                        RoleModel.name == SUPER_ADMIN_ROLE_NAME,
                    )
                )
            ).scalar()
            or False
        )
        if legacy:
            return True
        scoped = (
            self.db.query(
                exists().where(
                    and_(
                        UserRoleAssignmentModel.user_id == user_id,
                        UserRoleAssignmentModel.role_id == RoleModel.id,
                        UserRoleAssignmentModel.organization_id.is_(None),
                        UserRoleAssignmentModel.project_id.is_(None),
                        RoleModel.name == SUPER_ADMIN_ROLE_NAME,
                    )
                )
            ).scalar()
            or False
        )
        return scoped

    # -------------------------------------------------------------------
    # Permission catalog CRUD
    # -------------------------------------------------------------------

    def list_permissions(
        self, *, offset: int = 0, limit: int = 100,
    ) -> Tuple[List[PermissionModel], int]:
        total = self.db.query(func.count(PermissionModel.code)).scalar() or 0
        rows = (
            self.db.query(PermissionModel)
            .order_by(PermissionModel.code.asc())
            .offset(offset).limit(limit)
            .all()
        )
        return rows, total

    def get_permission(self, code: str) -> Optional[PermissionModel]:
        return (
            self.db.query(PermissionModel)
            .filter(PermissionModel.code == code)
            .first()
        )

    def create_permission(
        self, *, code: str, name: str, description: Optional[str],
        is_builtin: bool = False,
    ) -> PermissionModel:
        row = PermissionModel(
            code=code, name=name, description=description, is_builtin=is_builtin,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def update_permission(
        self, code: str, *, name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[PermissionModel]:
        row = self.get_permission(code)
        if row is None:
            return None
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        self.db.flush()
        return row

    def delete_permission(self, code: str) -> bool:
        row = self.get_permission(code)
        if row is None:
            return False
        # Cascade: remove role-grants and direct-grants for this code.
        self.db.execute(
            delete(RolePermissionModel).where(
                RolePermissionModel.permission_code == code
            )
        )
        self.db.execute(
            delete(UserPermissionModel).where(
                UserPermissionModel.permission_code == code
            )
        )
        self.db.delete(row)
        self.db.flush()
        return True

    # -------------------------------------------------------------------
    # Role queries
    # -------------------------------------------------------------------

    def get_role(self, role_id: int) -> Optional[RoleModel]:
        return (
            self.db.query(RoleModel).filter(RoleModel.id == role_id).first()
        )

    def get_role_by_name(self, name: str) -> Optional[RoleModel]:
        return (
            self.db.query(RoleModel).filter(RoleModel.name == name).first()
        )

    def list_role_permissions(self, role_id: int) -> List[str]:
        return sorted(
            r[0]
            for r in self.db.query(RolePermissionModel.permission_code)
            .filter(RolePermissionModel.role_id == role_id)
            .all()
        )

    # -------------------------------------------------------------------
    # Role-permission grants
    # -------------------------------------------------------------------

    def grant_permissions_to_role(
        self, role_id: int, codes: Iterable[str],
    ) -> int:
        existing = {
            r[0]
            for r in self.db.query(RolePermissionModel.permission_code)
            .filter(RolePermissionModel.role_id == role_id)
            .all()
        }
        added = 0
        for c in codes:
            if c in existing:
                continue
            self.db.add(RolePermissionModel(role_id=role_id, permission_code=c))
            existing.add(c)
            added += 1
        if added:
            self.db.flush()
        return added

    def revoke_permission_from_role(
        self, role_id: int, code: str,
    ) -> bool:
        row = (
            self.db.query(RolePermissionModel)
            .filter(
                RolePermissionModel.role_id == role_id,
                RolePermissionModel.permission_code == code,
            )
            .first()
        )
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    def replace_role_permissions(
        self, role_id: int, codes: Iterable[str],
    ) -> None:
        desired = set(codes)
        existing = {
            r[0]
            for r in self.db.query(RolePermissionModel.permission_code)
            .filter(RolePermissionModel.role_id == role_id)
            .all()
        }
        to_remove = existing - desired
        if to_remove:
            self.db.execute(
                delete(RolePermissionModel).where(
                    and_(
                        RolePermissionModel.role_id == role_id,
                        RolePermissionModel.permission_code.in_(to_remove),
                    )
                )
            )
        to_add = desired - existing
        for c in to_add:
            self.db.add(RolePermissionModel(role_id=role_id, permission_code=c))
        self.db.flush()

    # -------------------------------------------------------------------
    # User-role assignments
    # -------------------------------------------------------------------

    def list_roles_for_user(self, user_id: str) -> List[RoleModel]:
        return (
            self.db.query(RoleModel)
            .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
            .filter(UserRoleModel.user_id == user_id)
            .order_by(RoleModel.name.asc())
            .all()
        )

    def assign_role_to_user(
        self, user_id: str, role_id: int, *, actor_id: Optional[str] = None,
    ) -> bool:
        existing = (
            self.db.query(UserRoleModel)
            .filter(
                UserRoleModel.user_id == user_id,
                UserRoleModel.role_id == role_id,
            )
            .first()
        )
        if existing is not None:
            return False
        self.db.add(
            UserRoleModel(user_id=user_id, role_id=role_id, created_by=actor_id)
        )
        self.db.flush()
        return True

    def unassign_role_from_user(self, user_id: str, role_id: int) -> bool:
        row = (
            self.db.query(UserRoleModel)
            .filter(
                UserRoleModel.user_id == user_id,
                UserRoleModel.role_id == role_id,
            )
            .first()
        )
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    def count_users_with_role(self, role_id: int) -> int:
        # Joined count against users.deleted_at so soft-deleted holders don't
        # count toward the lockout protection. Local import to avoid cycles.
        from ..models.user import UserModel
        return (
            self.db.query(func.count(UserRoleModel.user_id))
            .join(UserModel, UserModel.id == UserRoleModel.user_id)
            .filter(UserRoleModel.role_id == role_id)
            .filter(UserModel.deleted_at.is_(None))
            .scalar()
        ) or 0

    # -------------------------------------------------------------------
    # Direct user-permission grants
    # -------------------------------------------------------------------

    def list_direct_permissions_for_user(self, user_id: str) -> List[str]:
        return sorted(
            r[0]
            for r in self.db.query(UserPermissionModel.permission_code)
            .filter(UserPermissionModel.user_id == user_id)
            .all()
        )

    def grant_permission_to_user(
        self, user_id: str, code: str, *, actor_id: Optional[str] = None,
    ) -> bool:
        existing = (
            self.db.query(UserPermissionModel)
            .filter(
                UserPermissionModel.user_id == user_id,
                UserPermissionModel.permission_code == code,
            )
            .first()
        )
        if existing is not None:
            return False
        self.db.add(
            UserPermissionModel(
                user_id=user_id, permission_code=code, created_by=actor_id,
            )
        )
        self.db.flush()
        return True

    def revoke_permission_from_user(self, user_id: str, code: str) -> bool:
        row = (
            self.db.query(UserPermissionModel)
            .filter(
                UserPermissionModel.user_id == user_id,
                UserPermissionModel.permission_code == code,
            )
            .first()
        )
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    # -------------------------------------------------------------------
    # Doc 41 — scoped role assignments (user_role_assignments)
    # -------------------------------------------------------------------

    def assign_scoped_role(
        self,
        *,
        user_id: str,
        role_id: int,
        organization_id: Optional[str] = None,
        project_id: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> Optional[UserRoleAssignmentModel]:
        """Create a (user, role, scope) row.

        Returns the new row, or the existing one if a duplicate (user,
        role, scope) tuple already exists. Scope rules:

          * Both ``organization_id`` and ``project_id`` NULL → global scope.
          * Exactly one set    → org or project scope.
          * Both set           → caller error; raises ``ValueError``.

        Caller is responsible for the caller-vs-target authorization
        check (e.g. "does the current user actually have ``RBAC_ASSIGN``
        in this scope?"). This method only enforces structural rules.
        """
        if organization_id is not None and project_id is not None:
            raise ValueError(
                "user_role_assignment cannot carry both organization_id "
                "and project_id — pick one scope."
            )

        # Idempotent: if the same (user, role, scope) row already
        # exists, return it instead of duplicating.
        existing = (
            self.db.query(UserRoleAssignmentModel)
            .filter(
                UserRoleAssignmentModel.user_id == user_id,
                UserRoleAssignmentModel.role_id == role_id,
                UserRoleAssignmentModel.organization_id.is_(organization_id) if organization_id is None else UserRoleAssignmentModel.organization_id == organization_id,
                UserRoleAssignmentModel.project_id.is_(project_id) if project_id is None else UserRoleAssignmentModel.project_id == project_id,
            )
            .first()
        )
        if existing is not None:
            return existing

        row = UserRoleAssignmentModel(
            user_id=user_id,
            role_id=role_id,
            organization_id=organization_id,
            project_id=project_id,
            created_by=actor_id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_scoped_assignment(
        self, assignment_id: int,
    ) -> Optional[UserRoleAssignmentModel]:
        return (
            self.db.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.id == assignment_id)
            .first()
        )

    def revoke_scoped_assignment(self, assignment_id: int) -> bool:
        row = self.get_scoped_assignment(assignment_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.flush()
        return True

    def list_scoped_assignments_for_user(
        self, user_id: str,
    ) -> List[UserRoleAssignmentModel]:
        return (
            self.db.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.user_id == user_id)
            .order_by(UserRoleAssignmentModel.id.asc())
            .all()
        )

    def list_scoped_assignments_for_project(
        self, project_id: str,
    ) -> List[UserRoleAssignmentModel]:
        return (
            self.db.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.project_id == project_id)
            .order_by(UserRoleAssignmentModel.id.asc())
            .all()
        )

    def list_scoped_assignments_for_org(
        self, organization_id: str,
    ) -> List[UserRoleAssignmentModel]:
        return (
            self.db.query(UserRoleAssignmentModel)
            .filter(UserRoleAssignmentModel.organization_id == organization_id)
            .order_by(UserRoleAssignmentModel.id.asc())
            .all()
        )

    def count_global_super_admins(self) -> int:
        """Count users holding super_admin globally (legacy + scoped).

        Used by the lockout-protection guard: revoking the LAST
        super_admin must be rejected.
        """
        legacy = (
            self.db.query(func.count(UserRoleModel.user_id))
            .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
            .filter(RoleModel.name == SUPER_ADMIN_ROLE_NAME)
            .scalar() or 0
        )
        scoped = (
            self.db.query(func.count(UserRoleAssignmentModel.id))
            .join(RoleModel, RoleModel.id == UserRoleAssignmentModel.role_id)
            .filter(
                RoleModel.name == SUPER_ADMIN_ROLE_NAME,
                UserRoleAssignmentModel.organization_id.is_(None),
                UserRoleAssignmentModel.project_id.is_(None),
            )
            .scalar() or 0
        )
        return legacy + scoped

    # -------------------------------------------------------------------
    # Startup sync — idempotent, safe to call on every boot
    # -------------------------------------------------------------------

    def sync_builtin_permissions(self) -> Tuple[int, int]:
        """Upsert every code in ``BUILTIN_PERMISSIONS`` into the catalog,
        ensure the ``admin``/``member``/``viewer`` roles exist, and ensure
        the ``admin`` role holds every permission currently in the registry.

        Returns ``(permissions_inserted, role_grants_added)`` for logging.
        """
        permissions_inserted = 0
        for p in BUILTIN_PERMISSIONS:
            row = self.get_permission(p.code)
            if row is None:
                self.create_permission(
                    code=p.code,
                    name=p.name,
                    description=p.description,
                    is_builtin=True,
                )
                permissions_inserted += 1
            else:
                # Refresh built-in metadata so renames in code propagate.
                if row.name != p.name or row.description != p.description:
                    row.name = p.name
                    row.description = p.description
                if not row.is_builtin:
                    row.is_builtin = True
        self.db.flush()

        # Ensure seed roles exist (legacy + doc 41).
        for role_name, role_desc in (
            (ADMIN_ROLE_NAME, "Built-in superadmin role. Holds every permission. Cannot be deleted."),
            (MEMBER_ROLE_NAME, "Default role for project contributors."),
            (VIEWER_ROLE_NAME, "Read-only role."),
            (VENDOR_ROLE_NAME, "Vendor role (doc 33). Edits M/A/T/S on assigned projects, no lifecycle / RBAC / master-data access."),
            # Doc 41 — scoped roles.
            (SUPER_ADMIN_ROLE_NAME, "Doc 41 super_admin. Holds every permission including USERS_GRANT_SUPERADMIN."),
            (ORG_ADMIN_ROLE_NAME, "Doc 41 org_admin. Manages users + projects within their vendor (organization)."),
            (PROJECT_ADMIN_ROLE_NAME, "Doc 41 project_admin. Manages task content + members on a single project."),
            (PROJECT_MEMBER_ROLE_NAME, "Doc 41 project_member. Read project, contribute task updates, comment + attach."),
            (DIVISION_MEMBER_ROLE_NAME, "Doc 41 division_member. Read-only on assigned projects (workbox / approval surface lands later)."),
        ):
            existing = self.get_role_by_name(role_name)
            if existing is None:
                self.db.add(RoleModel(
                    name=role_name, description=role_desc, builtin=True,
                ))
        self.db.flush()

        admin_role = self.get_role_by_name(ADMIN_ROLE_NAME)
        member_role = self.get_role_by_name(MEMBER_ROLE_NAME)
        viewer_role = self.get_role_by_name(VIEWER_ROLE_NAME)
        vendor_role = self.get_role_by_name(VENDOR_ROLE_NAME)
        super_admin_role = self.get_role_by_name(SUPER_ADMIN_ROLE_NAME)
        org_admin_role = self.get_role_by_name(ORG_ADMIN_ROLE_NAME)
        project_admin_role = self.get_role_by_name(PROJECT_ADMIN_ROLE_NAME)
        project_member_role = self.get_role_by_name(PROJECT_MEMBER_ROLE_NAME)
        division_member_role = self.get_role_by_name(DIVISION_MEMBER_ROLE_NAME)

        # super_admin holds everything (replaces what 'admin' used to be).
        # The legacy 'admin' role keeps the same superset for backwards
        # compat — see doc 41 decision log E.
        self.grant_permissions_to_role(super_admin_role.id, SUPER_ADMIN_ROLE_PERMISSIONS)
        # Legacy 'admin' role: same as super_admin for back-compat. (We
        # do NOT downgrade it to ADMIN_FULL_ROLE_PERMISSIONS — pre-doc-41
        # users with the 'admin' role expect the full power; doc 41
        # introduces 'super_admin' as the new top-tier and 'admin' is
        # left untouched for compat. Future doc may swap admin to
        # ADMIN_FULL_ROLE_PERMISSIONS once the FE is migrated.)
        added = self.grant_permissions_to_role(admin_role.id, ADMIN_ROLE_PERMISSIONS)

        # Member / viewer / vendor (legacy) — seed only if empty.
        if not self.list_role_permissions(member_role.id):
            self.grant_permissions_to_role(member_role.id, MEMBER_ROLE_PERMISSIONS)
        if not self.list_role_permissions(viewer_role.id):
            self.grant_permissions_to_role(viewer_role.id, VIEWER_ROLE_PERMISSIONS)
        if not self.list_role_permissions(vendor_role.id):
            self.grant_permissions_to_role(vendor_role.id, VENDOR_ROLE_PERMISSIONS)

        # Doc 41 scoped roles — seed only if empty.
        if not self.list_role_permissions(org_admin_role.id):
            self.grant_permissions_to_role(org_admin_role.id, ORG_ADMIN_ROLE_PERMISSIONS)
        if not self.list_role_permissions(project_admin_role.id):
            self.grant_permissions_to_role(project_admin_role.id, PROJECT_ADMIN_ROLE_PERMISSIONS)
        if not self.list_role_permissions(project_member_role.id):
            self.grant_permissions_to_role(project_member_role.id, PROJECT_MEMBER_ROLE_PERMISSIONS)
        if not self.list_role_permissions(division_member_role.id):
            self.grant_permissions_to_role(division_member_role.id, DIVISION_MEMBER_ROLE_PERMISSIONS)

        self.db.flush()
        return permissions_inserted, added
