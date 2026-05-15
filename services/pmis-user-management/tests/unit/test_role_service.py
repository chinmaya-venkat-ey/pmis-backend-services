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
    from app.services.role_service import RoleBuiltinImmutableError, RoleService

    svc = RoleService(MagicMock())
    svc.repo.get_role = MagicMock(return_value=_make_role(name="admin", builtin=True))

    with pytest.raises(RoleBuiltinImmutableError):
        svc.delete(1)


def test_replace_permissions_blocks_super_admin_grant_on_non_super_admin():
    """Granting users:grant_superadmin to the `admin` role must raise."""
    from app.services.role_service import (
        RoleService,
        SuperAdminGrantRestrictedError,
    )

    svc = RoleService(MagicMock())
    svc.repo.get_role = MagicMock(return_value=_make_role(name=ADMIN_ROLE))

    with pytest.raises(SuperAdminGrantRestrictedError):
        svc.replace_role_permissions(
            1,
            RolePermissionsReplaceRequest(
                permissions=[USERS_READ, USERS_GRANT_SUPERADMIN],
            ),
        )


def test_replace_permissions_allows_super_admin_grant_on_super_admin():
    from app.services.role_service import RoleService

    svc = RoleService(MagicMock())
    super_role = _make_role(role_id=99, name=SUPER_ADMIN_ROLE)
    svc.repo.get_role = MagicMock(return_value=super_role)
    svc.repo.replace_role_permissions = MagicMock()
    svc.repo.list_role_permissions = MagicMock(return_value=[USERS_GRANT_SUPERADMIN])

    role, perms = svc.replace_role_permissions(
        99,
        RolePermissionsReplaceRequest(permissions=[USERS_GRANT_SUPERADMIN]),
    )
    assert role is super_role
    assert USERS_GRANT_SUPERADMIN in perms


def test_grant_single_permission_blocks_super_admin_grant_on_non_super_admin():
    from app.services.role_service import (
        RoleService,
        SuperAdminGrantRestrictedError,
    )

    svc = RoleService(MagicMock())
    svc.repo.get_role = MagicMock(return_value=_make_role(name="org_admin"))

    with pytest.raises(SuperAdminGrantRestrictedError):
        svc.grant_permission_to_role(1, USERS_GRANT_SUPERADMIN)
