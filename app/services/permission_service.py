"""PermissionService — permission-catalog CRUD + by-module grouping + per-user effective lookups."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.permission import Permission
from app.repositories.rbac_repository import RbacRepository
from app.schemas.permission import (
    EffectivePermissionsResponse,
    PermissionCreateRequest,
    PermissionUpdateRequest,
    PermissionsByModuleResponse,
)


class PermissionNotFoundError(NotFoundError):
    default_code = "PERMISSION_NOT_FOUND"


class PermissionCodeConflictError(ConflictError):
    default_code = "PERMISSION_CODE_CONFLICT"


class PermissionBuiltinImmutableError(ConflictError):
    default_code = "PERMISSION_BUILTIN_IMMUTABLE"


class PermissionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = RbacRepository(db)

    # ------------------------------------------------------------------ CRUD

    def list_(self) -> List[Permission]:
        return self.repo.list_permissions()

    def get_by_code(self, code: str) -> Permission:
        row = self.repo.get_permission(code)
        if row is None:
            raise PermissionNotFoundError(f"Permission code {code!r} not found")
        return row

    def create(self, payload: PermissionCreateRequest) -> Permission:
        if self.repo.get_permission(payload.code) is not None:
            raise PermissionCodeConflictError(
                f"Permission code {payload.code!r} already exists",
                details={"code": payload.code},
            )
        row = self.repo.create_permission(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            is_builtin=False,
        )
        # A1 (2026-06-02 audit, part 3): auto-grant every new permission code
        # to admin and super_admin. After the `_is_admin` short-circuit removal
        # in Phase 4, these tiers must explicitly hold every code or they will
        # be 403'd on any new gate. Reserved codes (A7) are excluded so they
        # can never be granted via the runtime API.
        from app.core.permissions import (
            ADMIN_ROLE,
            RESERVED_DIRECT_GRANT_CODES,
            SUPER_ADMIN_ROLE,
        )
        if payload.code not in RESERVED_DIRECT_GRANT_CODES:
            for role_name in (SUPER_ADMIN_ROLE, ADMIN_ROLE):
                role = self.repo.get_role_by_name(role_name)
                if role is not None:
                    self.repo.grant_permissions_to_role(role.id, [payload.code])
        self.db.commit()
        return row

    def update(self, code: str, payload: PermissionUpdateRequest) -> Permission:
        row = self.get_by_code(code)
        self.repo.update_permission(row, name=payload.name, description=payload.description)
        self.db.commit()
        return row

    def delete(self, code: str) -> Permission:
        row = self.get_by_code(code)
        if row.is_builtin:
            raise PermissionBuiltinImmutableError(
                f"Cannot delete builtin permission {code!r}",
            )
        self.repo.delete_permission(code)
        self.db.commit()
        return row

    # ------------------------------------------------------------------ by-module grouping

    def by_module(self) -> PermissionsByModuleResponse:
        """Group permissions by their domain prefix (text before the colon)."""
        modules: Dict[str, List[Permission]] = defaultdict(list)
        for perm in self.repo.list_permissions():
            domain, _, _ = perm.code.partition(":")
            modules[domain or "other"].append(perm)
        # Sort each module's perms for stable output
        for codes in modules.values():
            codes.sort(key=lambda p: p.code)
        return PermissionsByModuleResponse(modules=dict(sorted(modules.items())))

    # ------------------------------------------------------------------ effective lookups

    def effective_for_user(self, user_id: str) -> EffectivePermissionsResponse:
        perms = sorted(self.repo.effective_permissions_for_user(user_id))
        is_admin = self.repo.user_has_admin_role(user_id)
        return EffectivePermissionsResponse(
            user_id=user_id, permissions=perms, is_admin=is_admin,
        )

    # ------------------------------------------------------------------ direct user grants

    def grant_to_user(self, user_id: str, code: str, *, caller_user_id: str) -> EffectivePermissionsResponse:
        # Ensure the perm exists; raise 404 otherwise.
        self.get_by_code(code)
        # Round-8 C1: reserved codes (currently {users:grant_superadmin})
        # can only be carried by the super_admin role itself — seeded by the
        # bootstrap migration. Direct user grants of reserved codes are
        # refused outright, regardless of caller tier (matches monolith F2
        # guard in RBAC_GUIDE.md:150,319).
        from app.core.errors import ForbiddenError
        from app.core.permissions import RESERVED_DIRECT_GRANT_CODES

        if code in RESERVED_DIRECT_GRANT_CODES:
            raise ForbiddenError(
                f"Permission {code!r} is reserved and cannot be granted "
                f"directly to a user.",
                code="RESERVED_PERMISSION",
                details={"code": code},
            )
        self.repo.grant_permission_to_user(user_id, code, granted_by_user_id=caller_user_id)
        self.db.commit()
        return self.effective_for_user(user_id)

    def revoke_from_user(self, user_id: str, code: str) -> EffectivePermissionsResponse:
        self.repo.revoke_permission_from_user(user_id, code)
        self.db.commit()
        return self.effective_for_user(user_id)
