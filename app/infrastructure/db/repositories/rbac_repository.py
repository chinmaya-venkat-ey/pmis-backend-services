"""Repository for the DB-driven RBAC tables (doc 21 part B).

Single class managing CRUD on permissions, role-permission grants,
user-role assignments, and direct user-permission grants. Centralizes
both the read (effective permissions for a user) and write paths so the
rest of the codebase doesn't reach into individual model classes.

All writes flush but do NOT commit — caller owns the transaction.
"""
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, delete, exists, func
from sqlalchemy.orm import Session

from ....core.permissions import (
    ADMIN_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
    VENDOR_ROLE_NAME,
    VENDOR_ROLE_PERMISSIONS,
    ADMIN_ROLE_PERMISSIONS,
    BUILTIN_PERMISSIONS,
    MEMBER_ROLE_NAME,
    MEMBER_ROLE_PERMISSIONS,
    VIEWER_ROLE_NAME,
    VIEWER_ROLE_PERMISSIONS,
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
        """Union of role-derived and direct grants for the user."""
        if user_id is None:
            return set()
        # Role-derived
        role_codes = {
            r[0]
            for r in self.db.query(RolePermissionModel.permission_code)
            .join(UserRoleModel, UserRoleModel.role_id == RolePermissionModel.role_id)
            .filter(UserRoleModel.user_id == user_id)
            .all()
        }
        direct_codes = {
            r[0]
            for r in self.db.query(UserPermissionModel.permission_code)
            .filter(UserPermissionModel.user_id == user_id)
            .all()
        }
        return role_codes | direct_codes

    def user_has_admin_role(self, user_id: str) -> bool:
        """True iff the user holds admin or super_admin globally.

        Doc 41 widens this to include super_admin (a strict superset of
        admin) and to honour global rows in ``user_role_assignments``.
        """
        if user_id is None:
            return False
        admin_names = (ADMIN_ROLE_NAME, SUPER_ADMIN_ROLE_NAME)
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

        # Ensure seed roles exist.
        for role_name, role_desc in (
            (ADMIN_ROLE_NAME, "Built-in superadmin role. Holds every permission. Cannot be deleted."),
            (MEMBER_ROLE_NAME, "Default role for project contributors."),
            (VIEWER_ROLE_NAME, "Read-only role."),
            (VENDOR_ROLE_NAME, "Vendor role (doc 33). Edits M/A/T/S on assigned projects, no lifecycle / RBAC / master-data access."),
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

        # Admin role holds everything currently registered.
        added = self.grant_permissions_to_role(admin_role.id, ADMIN_ROLE_PERMISSIONS)
        # Member / viewer / vendor roles get their seed sets if currently empty
        # (don't overwrite admin edits to these roles).
        if not self.list_role_permissions(member_role.id):
            self.grant_permissions_to_role(member_role.id, MEMBER_ROLE_PERMISSIONS)
        if not self.list_role_permissions(viewer_role.id):
            self.grant_permissions_to_role(viewer_role.id, VIEWER_ROLE_PERMISSIONS)
        if not self.list_role_permissions(vendor_role.id):
            self.grant_permissions_to_role(vendor_role.id, VENDOR_ROLE_PERMISSIONS)
        self.db.flush()
        return permissions_inserted, added
