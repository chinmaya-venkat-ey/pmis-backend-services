"""RoleService — role CRUD + role-permission management.

Round-8 hardening (monolith parity, RBAC_GUIDE.md L1/L2 lock + F2 reserved):

  - The `admin` and `super_admin` role rows are LOCKED at runtime. Their
    `name` / `description` / permission-set are exclusively maintained by
    the bootstrap migration. Every mutation path on these rows is rejected
    with `LockedRoleError`.
  - `users:grant_superadmin` (and any future RESERVED_DIRECT_GRANT_CODES)
    cannot be added to ANY role row via the runtime API. Only the seed
    can place it on super_admin.
  - Cannot delete a `builtin=True` role (legacy guard, kept).
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import (
    LOCKED_ROLE_NAMES,
    RESERVED_DIRECT_GRANT_CODES,
    SUPER_ADMIN_ROLE,
    USERS_GRANT_SUPERADMIN,
)
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


class LockedRoleError(ForbiddenError):
    """Round-8 L1/L2: cannot modify the `admin` or `super_admin` role at runtime."""

    default_code = "LOCKED_ROLE"


class SuperAdminGrantRestrictedError(ConflictError):
    default_code = "SUPER_ADMIN_GRANT_RESTRICTED"


class ReservedPermissionError(ForbiddenError):
    """Round-8 F2: codes in RESERVED_DIRECT_GRANT_CODES cannot be moved
    onto any role via runtime API."""

    default_code = "RESERVED_PERMISSION"


class CallerCannotGrantPermissionsError(ForbiddenError):
    """§3.4.4 (2026-06-02 audit): a runtime caller may not place codes on
    a role that the caller does not themselves hold. Closes the
    role-stuffing path (admin holds roles:update + permissions:manage →
    cannot inflate a custom role beyond admin's own capability set).
    """

    default_code = "CALLER_CANNOT_GRANT_PERMISSIONS"


def _assert_role_unlocked(row: Role) -> None:
    """Round-8 L1/L2: the admin + super_admin rows are immutable at runtime.

    Their name / description / permission set is exclusively maintained
    by the bootstrap data-migration. Any runtime mutation is refused.
    """
    if row.name in LOCKED_ROLE_NAMES:
        raise LockedRoleError(
            f"The built-in role {row.name!r} cannot be modified at runtime. "
            f"Its permission set is maintained by the bootstrap migration.",
            details={"role": row.name},
        )


class RoleService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = RbacRepository(db)

    def _assert_codes_within_caller_capability(
        self,
        codes: Iterable[str],
        caller_user_id: Optional[str],
        role_name: str,
    ) -> None:
        """§3.4.4 subset rule: every code being granted at runtime must be
        a code the caller themselves holds. Closes the role-stuffing
        elevation path (caller mints a custom role with codes they do not
        themselves hold, then assigns themselves to it).

        ``caller_user_id`` may be None only for bootstrap/migration code
        paths (no live HTTP request). The runtime routes always supply it.
        """
        codes_set = {c for c in codes if c}
        if not codes_set:
            return
        if caller_user_id is None:
            return  # Bootstrap context — migrations bypass this check.
        held = self.repo.effective_permissions_for_user(caller_user_id)
        missing = sorted(codes_set - held)
        if missing:
            raise CallerCannotGrantPermissionsError(
                f"Caller cannot grant code(s) {missing!r} to role "
                f"{role_name!r}: caller does not hold them.",
                details={
                    "role": role_name,
                    "missing_codes": missing,
                    "caller_user_id": caller_user_id,
                },
            )

    def list_(self) -> List[Role]:
        return self.repo.list_roles()

    def get_by_id(self, role_id: int) -> Role:
        row = self.repo.get_role(role_id)
        if row is None:
            raise RoleNotFoundError(f"Role {role_id} not found")
        return row

    def create(
        self,
        payload: RoleCreateRequest,
        *,
        caller_user_id: Optional[str] = None,
    ) -> Role:
        # Round-8: prevent re-creation of a locked-role name as a non-builtin
        # row (would create a same-name shadow that the locks wouldn't catch).
        if payload.name in LOCKED_ROLE_NAMES:
            raise LockedRoleError(
                f"Role name {payload.name!r} is reserved.",
                details={"name": payload.name},
            )
        if self.repo.get_role_by_name(payload.name) is not None:
            raise RoleNameConflictError(
                f"Role name {payload.name!r} already exists",
                details={"name": payload.name},
            )
        if payload.permissions:
            self._assert_codes_within_caller_capability(
                payload.permissions, caller_user_id, payload.name,
            )
        row = self.repo.create_role(
            name=payload.name,
            description=payload.description,
            builtin=payload.builtin,
        )
        if payload.permissions:
            self.repo.grant_permissions_to_role(row.id, payload.permissions)
        self.db.commit()
        return row

    def update(
        self,
        role_id: int,
        payload: RoleUpdateRequest,
        *,
        caller_user_id: Optional[str] = None,
    ) -> Role:
        row = self.get_by_id(role_id)
        _assert_role_unlocked(row)
        # A3 (2026-06-02 audit): refuse to rename a non-locked role TO
        # admin/super_admin. Combined with the existing LOCKED_ROLE_NAMES
        # check on .create(), this prevents any runtime path from
        # promoting a role to admin-tier.
        if payload.name is not None and payload.name in LOCKED_ROLE_NAMES:
            raise LockedRoleError(
                f"Cannot rename a role to the reserved name {payload.name!r}.",
                details={"name": payload.name},
            )
        self.repo.update_role(row, name=payload.name, description=payload.description)
        if payload.permissions is not None:
            reserved = RESERVED_DIRECT_GRANT_CODES & set(payload.permissions)
            if reserved:
                raise ReservedPermissionError(
                    f"Cannot place reserved permission(s) {sorted(reserved)} on role {row.name!r}.",
                    details={"role": row.name, "reserved_codes": sorted(reserved)},
                )
            self._assert_codes_within_caller_capability(
                payload.permissions, caller_user_id, row.name,
            )
            self.repo.replace_role_permissions(role_id, payload.permissions)
        self.db.commit()
        return row

    def delete(self, role_id: int) -> Role:
        row = self.get_by_id(role_id)
        _assert_role_unlocked(row)
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
        *,
        caller_user_id: Optional[str] = None,
    ) -> Tuple[Role, List[str]]:
        row = self.get_by_id(role_id)
        _assert_role_unlocked(row)  # round-8 H2: cannot empty super_admin's perms
        # Reserved codes (users:grant_superadmin etc.) may never appear in
        # a replace payload — they live on super_admin only, via the seed.
        # The check fires regardless of target role since the target cannot
        # be super_admin/admin here (locked-role guard rejected that above).
        reserved = RESERVED_DIRECT_GRANT_CODES & set(payload.permissions)
        if reserved:
            raise ReservedPermissionError(
                f"Cannot place reserved permission(s) {sorted(reserved)} on "
                f"role {row.name!r}. Reserved codes are maintained only by "
                f"the bootstrap migration.",
                details={"role": row.name, "reserved_codes": sorted(reserved)},
            )
        # Legacy guard kept for clarity even though L1/L2 covers it.
        if row.name != SUPER_ADMIN_ROLE and USERS_GRANT_SUPERADMIN in payload.permissions:
            raise SuperAdminGrantRestrictedError(
                f"Cannot grant {USERS_GRANT_SUPERADMIN!r} to role {row.name!r}",
            )
        self._assert_codes_within_caller_capability(
            payload.permissions, caller_user_id, row.name,
        )
        self.repo.replace_role_permissions(role_id, payload.permissions)
        self.db.commit()
        return row, self.repo.list_role_permissions(role_id)

    def grant_permission_to_role(
        self,
        role_id: int,
        code: str,
        *,
        caller_user_id: Optional[str] = None,
    ) -> Tuple[Role, List[str]]:
        row = self.get_by_id(role_id)
        _assert_role_unlocked(row)  # round-8 C3: cannot mutate admin/super_admin
        if code in RESERVED_DIRECT_GRANT_CODES:
            raise ReservedPermissionError(
                f"Cannot grant reserved permission {code!r} to any role at runtime.",
                details={"role": row.name, "code": code},
            )
        self._assert_codes_within_caller_capability(
            [code], caller_user_id, row.name,
        )
        # Legacy SuperAdminGrantRestrictedError path is now subsumed by the
        # _assert_role_unlocked guard (super_admin row is locked) plus the
        # reserved-code check.
        self.repo.grant_permissions_to_role(role_id, [code])
        self.db.commit()
        return row, self.repo.list_role_permissions(role_id)

    def revoke_permission_from_role(self, role_id: int, code: str) -> Tuple[Role, List[str]]:
        row = self.get_by_id(role_id)
        _assert_role_unlocked(row)  # round-8 H1: cannot strip super_admin's perms
        self.repo.revoke_permission_from_role(role_id, code)
        self.db.commit()
        return row, self.repo.list_role_permissions(role_id)
