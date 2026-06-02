"""Unit tests for RoleService — covers the three business rules:
  - Role names must be unique (RoleNameConflictError on duplicate create).
  - Cannot delete a builtin role (RoleBuiltinImmutableError).
  - Cannot grant `users:grant_superadmin` to anything below super_admin
    (SuperAdminGrantRestrictedError).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.permissions import (
    ADMIN_ROLE,
    SUPER_ADMIN_ROLE,
    USERS_GRANT_SUPERADMIN,
    USERS_READ,
)
from app.schemas.role import RoleCreateRequest, RolePermissionsReplaceRequest


def _make_role(*, role_id=1, name="custom", builtin=False):
    row = MagicMock(name=f"Role({name})")
    row.id = role_id
    row.name = name
    row.builtin = builtin
    return row


def test_create_role_name_conflict():
    from app.services.role_service import RoleNameConflictError, RoleService

    svc = RoleService(MagicMock())
    svc.repo.get_role_by_name = MagicMock(return_value=_make_role(name="dup"))

    with pytest.raises(RoleNameConflictError):
        svc.create(RoleCreateRequest(name="dup"))


def test_delete_builtin_role_blocked():
    """Round-8: deleting 'admin' is blocked by the locked-role guard, which
    fires before the builtin check. A custom builtin role would still raise
    RoleBuiltinImmutableError; admin/super_admin raise LockedRoleError."""
    from app.services.role_service import LockedRoleError, RoleService

    svc = RoleService(MagicMock())
    svc.repo.get_role = MagicMock(return_value=_make_role(name="admin", builtin=True))

    with pytest.raises(LockedRoleError):
        svc.delete(1)


def test_replace_permissions_blocks_super_admin_grant_on_non_super_admin():
    """Round-8: `admin` is now a locked role — its permission set can't be
    mutated at runtime at all. The locked-role guard fires first, so the
    legacy SuperAdminGrantRestrictedError path is unreachable for admin."""
    from app.services.role_service import LockedRoleError, RoleService

    svc = RoleService(MagicMock())
    svc.repo.get_role = MagicMock(return_value=_make_role(name=ADMIN_ROLE))

    with pytest.raises(LockedRoleError):
        svc.replace_role_permissions(
            1,
            RolePermissionsReplaceRequest(
                permissions=[USERS_READ, USERS_GRANT_SUPERADMIN],
            ),
        )


def test_replace_permissions_on_super_admin_blocked_by_lock():
    """Round-8: the super_admin row is also locked at runtime — its permission
    set is maintained only by the bootstrap data-migration. Even granting
    USERS_GRANT_SUPERADMIN (a code super_admin already holds) is refused."""
    from app.services.role_service import LockedRoleError, RoleService

    svc = RoleService(MagicMock())
    super_role = _make_role(role_id=99, name=SUPER_ADMIN_ROLE)
    svc.repo.get_role = MagicMock(return_value=super_role)

    with pytest.raises(LockedRoleError):
        svc.replace_role_permissions(
            99,
            RolePermissionsReplaceRequest(permissions=[USERS_GRANT_SUPERADMIN]),
        )


def test_grant_single_permission_blocks_reserved_grant_on_non_super_admin():
    """Round-8: USERS_GRANT_SUPERADMIN is now in RESERVED_DIRECT_GRANT_CODES,
    so it can't be placed on any role at runtime. The legacy
    SuperAdminGrantRestrictedError path is subsumed by ReservedPermissionError
    (for non-locked roles) and LockedRoleError (for admin/super_admin)."""
    from app.services.role_service import (
        ReservedPermissionError,
        RoleService,
    )

    svc = RoleService(MagicMock())
    svc.repo.get_role = MagicMock(return_value=_make_role(name="org_admin"))

    with pytest.raises(ReservedPermissionError):
        svc.grant_permission_to_role(1, USERS_GRANT_SUPERADMIN)
