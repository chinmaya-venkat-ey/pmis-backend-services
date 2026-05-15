"""RoleService — role CRUD + role-permission management.

Thin wrapper over RbacRepository's role + role-permission methods. Adds the
business rules:
  - Role names must be unique (DB enforces; service surfaces a friendly error)
  - Cannot delete a builtin role
  - Cannot grant `users:grant_superadmin` to anything below `super_admin`
"""
from __future__ import annotations

from typing import List, Tuple

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.permissions import SUPER_ADMIN_ROLE, USERS_GRANT_SUPERADMIN
from app.models.role import Role
from app.repositories.rbac_repository import RbacRepository
from app.schemas.role import (
    RoleCreateRequest,
    RolePermissionsReplaceRequest,
    RoleUpdateRequest,
)


class RoleNotFoundError(NotFoundError):
    default_code = "ROLE_NOT_FOUND"


class RoleNameConflictError(ConflictError):
    default_code = "ROLE_NAME_CONFLICT"


class RoleBuiltinImmutableError(ConflictError):
    """Cannot delete a builtin role (super_admin, admin, etc.)."""

    default_code = "ROLE_BUILTIN_IMMUTABLE"


class SuperAdminGrantRestrictedError(ConflictError):
    default_code = "SUPER_ADMIN_GRANT_RESTRICTED"


class RoleService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = RbacRepository(db)

    def list_(self) -> List[Role]:
        return self.repo.list_roles()

    def get_by_id(self, role_id: int) -> Role:
        row = self.repo.get_role(role_id)
        if row is None:
            raise RoleNotFoundError(f"Role {role_id} not found")
        return row

    def create(self, payload: RoleCreateRequest) -> Role:
        if self.repo.get_role_by_name(payload.name) is not None:
            raise RoleNameConflictError(
                f"Role name {payload.name!r} already exists",
                details={"name": payload.name},
            )
        row = self.repo.create_role(
            name=payload.name,
            description=payload.description,
            builtin=False,
        )
        self.db.commit()
        return row

    def update(self, role_id: int, payload: RoleUpdateRequest) -> Role:
        row = self.get_by_id(role_id)
        self.repo.update_role(row, description=payload.description)
        self.db.commit()
        return row

    def delete(self, role_id: int) -> Role:
        row = self.get_by_id(role_id)
        if row.builtin:
            raise RoleBuiltinImmutableError(
                f"Cannot delete builtin role {row.name!r}",
            )
        self.repo.delete_role(role_id)
        self.db.commit()
        return row

    # ------------------------------------------------------------------ role-permission grants

    def list_role_permissions(self, role_id: int) -> Tuple[Role, List[str]]:
        row = self.get_by_id(role_id)
        return row, self.repo.list_role_permissions(role_id)

    def replace_role_permissions(
        self,
        role_id: int,
        payload: RolePermissionsReplaceRequest,
    ) -> Tuple[Role, List[str]]:
        row = self.get_by_id(role_id)
        # Guard: only super_admin can hold users:grant_superadmin
        if row.name != SUPER_ADMIN_ROLE and USERS_GRANT_SUPERADMIN in payload.permissions:
            raise SuperAdminGrantRestrictedError(
                f"Cannot grant {USERS_GRANT_SUPERADMIN!r} to role {row.name!r} "
                "(only super_admin may hold it)",
            )
        self.repo.replace_role_permissions(role_id, payload.permissions)
        self.db.commit()
        return row, self.repo.list_role_permissions(role_id)

    def grant_permission_to_role(self, role_id: int, code: str) -> Tuple[Role, List[str]]:
        row = self.get_by_id(role_id)
        if row.name != SUPER_ADMIN_ROLE and code == USERS_GRANT_SUPERADMIN:
            raise SuperAdminGrantRestrictedError(
                f"Cannot grant {USERS_GRANT_SUPERADMIN!r} to role {row.name!r}",
            )
        self.repo.grant_permissions_to_role(role_id, [code])
        self.db.commit()
        return row, self.repo.list_role_permissions(role_id)

    def revoke_permission_from_role(self, role_id: int, code: str) -> Tuple[Role, List[str]]:
        row = self.get_by_id(role_id)
        self.repo.revoke_permission_from_role(role_id, code)
        self.db.commit()
        return row, self.repo.list_role_permissions(role_id)
