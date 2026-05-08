"""
Role routes - URL definitions with permission bindings.
"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.middleware.rbac import require_permission, require_authenticated
from ....core.permissions import (
    ADMIN_ROLE_NAME, SUPER_ADMIN_ROLE_NAME, RBAC_ASSIGN,
)
from ....core.response import format_error_response
from ....infrastructure.db.repositories.rbac_repository import RbacRepository
from ....infrastructure.db.session import get_db
from .controller import RoleController
from .schemas import (
    RoleCreateRequest,
    RoleUpdateRequest,
    RoleListQuery,
    RolePermissionsReplaceRequest,
)
from .permissions import (
    ROLES_CREATE,
    ROLES_READ,
    ROLES_UPDATE,
    ROLES_DELETE
)

router = APIRouter(prefix="/roles", tags=["roles"])


def _stamp(resp, *, successor: str):
    """Apply Deprecation + Link headers pointing at the master-router successor.

    Doc 21B follow-up: role + permission CRUD now lives under
    ``/api/v3/master/roles/*`` and ``/api/v3/master/permissions/*``. The
    legacy paths keep working during the FE migration window.
    """
    return BaseController.stamp_deprecation(resp, successor_path=successor)


@router.post(
    "/create",
    dependencies=[require_permission(ROLES_CREATE)],
    summary="Create role (DEPRECATED — use POST /api/v3/master/roles/create)",
    status_code=201
)
def create_role(
    request: Request,
    data: RoleCreateRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    return _stamp(
        RoleController.create(request, data, db),
        successor="/api/v3/master/roles/create",
    )


@router.get(
    "",
    dependencies=[require_permission(ROLES_READ)],
    summary="List roles (DEPRECATED — use GET /api/v3/master/roles)",
)
def list_roles(
    request: Request,
    offset: int = Query(1, ge=1, description="Page number (1-indexed)"),
    pageSize: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    query = RoleListQuery(offset=offset, pageSize=pageSize)
    return _stamp(
        RoleController.list(request, query, db),
        successor="/api/v3/master/roles",
    )


@router.get(
    "/{role_id}",
    dependencies=[require_permission(ROLES_READ)],
    summary="Get role (DEPRECATED — use GET /api/v3/master/roles/{id})",
)
def get_role(
    request: Request,
    role_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    return _stamp(
        RoleController.get(request, role_id, db),
        successor=f"/api/v3/master/roles/{role_id}",
    )


@router.patch(
    "/{role_id}",
    dependencies=[require_permission(ROLES_UPDATE)],
    summary="Update role (DEPRECATED — use PATCH /api/v3/master/roles/{id})",
)
def update_role(
    request: Request,
    role_id: int,
    data: RoleUpdateRequest,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    return _stamp(
        RoleController.update(request, role_id, data, db),
        successor=f"/api/v3/master/roles/{role_id}",
    )


@router.delete(
    "/{role_id}",
    dependencies=[require_permission(ROLES_DELETE)],
    summary="Delete role (DEPRECATED — use DELETE /api/v3/master/roles/{id})",
)
def delete_role(
    request: Request,
    role_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    return _stamp(
        RoleController.delete(request, role_id, db),
        successor=f"/api/v3/master/roles/{role_id}",
    )


# ---------------------------------------------------------------------------
# Role-permission management (doc 21 part B)
# ---------------------------------------------------------------------------

_LOCKED_ROLE_NAMES = frozenset({ADMIN_ROLE_NAME, SUPER_ADMIN_ROLE_NAME})


def _admin_role_guard(role) -> Dict[str, Any]:
    """Returns an error payload when the role is one of the locked
    built-in roles (admin / super_admin), else None.

    Both roles' permission sets are auto-managed by the startup sync —
    admin holds everything except users:grant_superadmin; super_admin
    holds everything. Manual mutation via the API would race the seed
    loop on next boot anyway, so it's refused outright.
    """
    if role is not None and role.name in _LOCKED_ROLE_NAMES:
        return format_error_response(
            "forbidden",
            f"The built-in '{role.name}' role's permission set is "
            "auto-managed and cannot be modified.",
        )
    return None


@router.get(
    "/{role_id}/permissions",
    dependencies=[require_permission(ROLES_READ)],
    summary=(
        "List a role's permissions "
        "(DEPRECATED — use GET /api/v3/master/roles/{id}/permissions)"
    ),
)
def list_role_permissions(
    request: Request, role_id: int, db: Session = Depends(get_db),
):
    repo = RbacRepository(db)
    role = repo.get_role(role_id)
    if role is None:
        return _stamp(
            BaseController.error(
                format_error_response("not_found", f"Role {role_id} not found."),
                status=404,
            ),
            successor=f"/api/v3/master/roles/{role_id}/permissions",
        )
    codes = repo.list_role_permissions(role_id)
    return _stamp(
        BaseController.ok(data={
            "_type": "RolePermissions",
            "_links": {
                "self": {
                    "href": f"/api/v3/master/roles/{role_id}/permissions",
                }
            },
            "roleId": role_id,
            "roleName": role.name,
            "permissions": codes,
        }),
        successor=f"/api/v3/master/roles/{role_id}/permissions",
    )


@router.put(
    "/{role_id}/permissions",
    dependencies=[require_permission(ROLES_UPDATE)],
    summary=(
        "Replace a role's permission set "
        "(DEPRECATED — use PUT /api/v3/master/roles/{id}/permissions)"
    ),
)
def replace_role_permissions(
    request: Request, role_id: int,
    data: RolePermissionsReplaceRequest,
    db: Session = Depends(get_db),
):
    repo = RbacRepository(db)
    role = repo.get_role(role_id)
    if role is None:
        return _stamp(
            BaseController.error(
                format_error_response("not_found", f"Role {role_id} not found."),
                status=404,
            ),
            successor=f"/api/v3/master/roles/{role_id}/permissions",
        )
    err = _admin_role_guard(role)
    if err is not None:
        return _stamp(
            BaseController.error(err, status=403),
            successor=f"/api/v3/master/roles/{role_id}/permissions",
        )
    # Reserved-permission guard: users:grant_superadmin can only be
    # held by the seeded super_admin role. Refuse to plant it on any
    # other role's permission set (which would create an alternate
    # path to the role-grant gate).
    from ....core.permissions import (
        SUPER_ADMIN_ROLE_NAME, USERS_GRANT_SUPERADMIN,
    )
    if (
        role.name != SUPER_ADMIN_ROLE_NAME
        and USERS_GRANT_SUPERADMIN in data.permissions
    ):
        return _stamp(
            BaseController.error(
                format_error_response(
                    "forbidden",
                    "users:grant_superadmin is reserved for the "
                    "super_admin role and cannot be granted to other roles.",
                ),
                status=403,
            ),
            successor=f"/api/v3/master/roles/{role_id}/permissions",
        )
    bogus = [c for c in data.permissions if repo.get_permission(c) is None]
    if bogus:
        return _stamp(
            BaseController.error(
                format_error_response(
                    "validation_error",
                    f"Unknown permission code(s): {', '.join(bogus)}",
                ),
                status=422,
            ),
            successor=f"/api/v3/master/roles/{role_id}/permissions",
        )
    repo.replace_role_permissions(role_id, list(dict.fromkeys(data.permissions)))
    db.commit()
    return _stamp(
        BaseController.ok(data={
            "roleId": role_id,
            "permissions": repo.list_role_permissions(role_id),
        }),
        successor=f"/api/v3/master/roles/{role_id}/permissions",
    )


@router.post(
    "/{role_id}/permissions/{code}",
    dependencies=[require_permission(ROLES_UPDATE)],
    summary=(
        "Grant a single permission to a role "
        "(DEPRECATED — use POST /api/v3/master/roles/{id}/permissions/{code})"
    ),
)
def grant_role_permission(
    request: Request, role_id: int, code: str,
    db: Session = Depends(get_db),
):
    successor = f"/api/v3/master/roles/{role_id}/permissions/{code}"
    repo = RbacRepository(db)
    role = repo.get_role(role_id)
    if role is None:
        return _stamp(
            BaseController.error(
                format_error_response("not_found", f"Role {role_id} not found."),
                status=404,
            ),
            successor=successor,
        )
    err = _admin_role_guard(role)
    if err is not None:
        return _stamp(BaseController.error(err, status=403), successor=successor)
    # Reserved-permission guard: users:grant_superadmin can only be
    # held by the seeded super_admin role.
    from ....core.permissions import (
        SUPER_ADMIN_ROLE_NAME, USERS_GRANT_SUPERADMIN,
    )
    if code == USERS_GRANT_SUPERADMIN and role.name != SUPER_ADMIN_ROLE_NAME:
        return _stamp(
            BaseController.error(
                format_error_response(
                    "forbidden",
                    "users:grant_superadmin is reserved for the "
                    "super_admin role and cannot be granted to other roles.",
                ),
                status=403,
            ),
            successor=successor,
        )
    if repo.get_permission(code) is None:
        return _stamp(
            BaseController.error(
                format_error_response(
                    "not_found", f"Permission {code} not found.",
                ),
                status=404,
            ),
            successor=successor,
        )
    repo.grant_permissions_to_role(role_id, [code])
    db.commit()
    return _stamp(
        BaseController.ok(data={
            "roleId": role_id,
            "permissions": repo.list_role_permissions(role_id),
        }),
        successor=successor,
    )


@router.delete(
    "/{role_id}/permissions/{code}",
    dependencies=[require_permission(ROLES_UPDATE)],
    summary=(
        "Revoke a single permission from a role "
        "(DEPRECATED — use DELETE /api/v3/master/roles/{id}/permissions/{code})"
    ),
)
def revoke_role_permission(
    request: Request, role_id: int, code: str,
    db: Session = Depends(get_db),
):
    successor = f"/api/v3/master/roles/{role_id}/permissions/{code}"
    repo = RbacRepository(db)
    role = repo.get_role(role_id)
    if role is None:
        return _stamp(
            BaseController.error(
                format_error_response("not_found", f"Role {role_id} not found."),
                status=404,
            ),
            successor=successor,
        )
    err = _admin_role_guard(role)
    if err is not None:
        return _stamp(BaseController.error(err, status=403), successor=successor)
    repo.revoke_permission_from_role(role_id, code)
    db.commit()
    return _stamp(BaseController.no_content(), successor=successor)
