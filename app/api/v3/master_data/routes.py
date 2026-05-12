"""Master-data router — user-mgmt slim slice.

Routes hosted here:
  - /api/v3/master/roles                  (delegates to ../roles handlers)
  - /api/v3/master/permissions            (delegates to ../permissions handlers)
  - /api/v3/master/permissions/by-module

Roles and permissions delegate to the existing legacy route handlers in
``app/api/v3/roles/`` and ``app/api/v3/permissions/`` — same pattern as
the monolith — so we don't duplicate the RBAC-management plumbing.

``/api/v3/master/notification_templates`` is owned by
PMIS-notification-service (doc 38). Other master-data slices (divisions,
vendors, etc.) stay on the monolith.
"""
from collections import defaultdict
from typing import Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.middleware.rbac import require_permission
from ....core.permissions import MASTER_DATA_MANAGE, MASTER_DATA_VIEW
from ....infrastructure.db.repositories.rbac_repository import RbacRepository
from ....infrastructure.db.session import get_db
from ....shared.datetime import iso_ist

# Delegates: legacy /roles + /permissions handlers.
from ..roles.routes import (
    create_role as _role_create,
    delete_role as _role_delete,
    get_role as _role_get,
    grant_role_permission as _role_grant_permission,
    list_role_permissions as _role_list_permissions,
    list_roles as _role_list,
    replace_role_permissions as _role_replace_permissions,
    revoke_role_permission as _role_revoke_permission,
    update_role as _role_update,
)
from ..roles.schemas import (
    RoleCreateRequest,
    RolePermissionsReplaceRequest,
    RoleUpdateRequest,
)
from ..permissions.routes import (
    create_permission as _perm_create,
    delete_permission as _perm_delete,
    get_permission as _perm_get,
    list_permissions as _perm_list,
    update_permission as _perm_update,
)
from ..permissions.schemas import (
    PermissionCreateRequest,
    PermissionUpdateRequest,
)

router = APIRouter(prefix="/master", tags=["master_data"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _without_deprecation(response: JSONResponse) -> JSONResponse:
    """Strip Deprecation/Link headers stamped by legacy handlers."""
    for h in ("Deprecation", "Link"):
        if h in response.headers:
            del response.headers[h]
    return response


# ---------------------------------------------------------------------------
# Roles — delegate to ../roles/routes.py.
# ---------------------------------------------------------------------------

@router.get(
    "/roles",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List roles (delegates to GET /api/v3/roles)",
)
def list_master_roles(
    request: Request,
    offset: int = 1,
    pageSize: int = 20,
    db: Session = Depends(get_db),
):
    sql_offset = (offset - 1) * pageSize if offset > 0 else 0
    return _without_deprecation(
        _role_list(
            request=request, offset=sql_offset, pageSize=pageSize, db=db,
        ),
    )


@router.get(
    "/roles/{role_id}",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="Get a role (delegates)",
)
def get_master_role(
    request: Request, role_id: int, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_get(request=request, role_id=role_id, db=db),
    )


@router.post(
    "/roles/create",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Create a role (delegates)",
    status_code=201,
)
def create_master_role(
    request: Request,
    data: RoleCreateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_create(request=request, data=data, db=db),
    )


@router.patch(
    "/roles/{role_id}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Update a role (delegates)",
)
def update_master_role(
    request: Request,
    role_id: int,
    data: RoleUpdateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_update(request=request, role_id=role_id, data=data, db=db),
    )


@router.delete(
    "/roles/{role_id}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Delete a role (admin role protected; delegates)",
)
def delete_master_role(
    request: Request, role_id: int, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_delete(request=request, role_id=role_id, db=db),
    )


@router.get(
    "/roles/{role_id}/permissions",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List a role's permissions (delegates)",
)
def list_master_role_permissions(
    request: Request, role_id: int, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_list_permissions(request=request, role_id=role_id, db=db),
    )


@router.put(
    "/roles/{role_id}/permissions",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Replace a role's permission set (delegates)",
)
def replace_master_role_permissions(
    request: Request,
    role_id: int,
    data: RolePermissionsReplaceRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_replace_permissions(
            request=request, role_id=role_id, data=data, db=db,
        ),
    )


@router.post(
    "/roles/{role_id}/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Grant a permission to a role (delegates)",
)
def grant_master_role_permission(
    request: Request, role_id: int, code: str,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_grant_permission(
            request=request, role_id=role_id, code=code, db=db,
        ),
    )


@router.delete(
    "/roles/{role_id}/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Revoke a permission from a role (delegates)",
)
def revoke_master_role_permission(
    request: Request, role_id: int, code: str,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _role_revoke_permission(
            request=request, role_id=role_id, code=code, db=db,
        ),
    )


# ---------------------------------------------------------------------------
# Permissions — delegate to ../permissions/routes.py.
# ---------------------------------------------------------------------------

@router.get(
    "/permissions",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List the permission catalog (delegates)",
)
def list_master_permissions(
    request: Request,
    offset: int = 1,
    pageSize: int = 100,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_list(
            request=request, offset=offset, pageSize=pageSize, db=db,
        ),
    )


@router.get(
    "/permissions/by-module",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="List the permission catalog grouped by module",
)
def list_master_permissions_by_module(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = RbacRepository(db)
    rows, total = repo.list_permissions(offset=0, limit=10_000)
    buckets: Dict[str, list] = defaultdict(list)
    for r in rows:
        module = r.code.split(":", 1)[0] if ":" in r.code else "_uncategorised"
        buckets[module].append({
            "_type": "Permission",
            "code": r.code,
            "name": r.name,
            "description": r.description,
            "isBuiltin": bool(r.is_builtin),
            "createdAt": iso_ist(r.created_at),
            "updatedAt": iso_ist(r.updated_at),
        })
    modules_list = [
        {
            "_type": "PermissionModule",
            "module": module,
            "count": len(perms),
            "permissions": sorted(perms, key=lambda p: p["code"]),
        }
        for module, perms in sorted(buckets.items(), key=lambda kv: kv[0])
    ]
    payload = {
        "_type": "PermissionsByModule",
        "_links": {"self": {"href": "/api/v3/master/permissions/by-module"}},
        "moduleCount": len(modules_list),
        "totalPermissions": total,
        "_embedded": {"modules": modules_list},
    }
    return BaseController.ok(data=payload)


@router.get(
    "/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_VIEW)],
    summary="Get a permission row (delegates)",
)
def get_master_permission(
    request: Request, code: str, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_get(request=request, code=code, db=db),
    )


@router.post(
    "/permissions/create",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Create a custom permission (delegates)",
    status_code=201,
)
def create_master_permission(
    request: Request,
    data: PermissionCreateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_create(request=request, data=data, db=db),
    )


@router.patch(
    "/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Edit a permission's name/description (delegates)",
)
def update_master_permission(
    request: Request,
    code: str,
    data: PermissionUpdateRequest,
    db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_update(request=request, code=code, data=data, db=db),
    )


@router.delete(
    "/permissions/{code}",
    dependencies=[require_permission(MASTER_DATA_MANAGE)],
    summary="Delete a permission (built-ins protected; delegates)",
)
def delete_master_permission(
    request: Request, code: str, db: Session = Depends(get_db),
):
    return _without_deprecation(
        _perm_delete(request=request, code=code, db=db),
    )

