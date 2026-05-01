"""Role routes - URL definitions with permission bindings."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ....core.middleware.rbac import require_permission
from ....infrastructure.db.session import get_db
from .controller import RoleController
from .permissions import ROLES_CREATE, ROLES_DELETE, ROLES_READ, ROLES_UPDATE
from .schemas import RoleCreateRequest, RoleListQuery, RoleUpdateRequest


router = APIRouter(prefix="/roles", tags=["roles"])


@router.post(
    "/create",
    dependencies=[require_permission(ROLES_CREATE)],
    summary="Create role",
    description="Create a new role.",
    status_code=201,
)
def create_role(
    request: Request,
    data: RoleCreateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create a new role. Requires ROLES_CREATE permission (admin only)."""
    return RoleController.create(request, data, db)


@router.get(
    "",
    dependencies=[require_permission(ROLES_READ)],
    summary="List roles",
    description="List all roles with pagination.",
)
def list_roles(
    request: Request,
    offset: int = Query(1, ge=1, description="Page number (1-indexed)"),
    pageSize: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List roles with pagination. Requires ROLES_READ permission."""
    query = RoleListQuery(offset=offset, pageSize=pageSize)
    return RoleController.list(request, query, db)


@router.get(
    "/{role_id}",
    dependencies=[require_permission(ROLES_READ)],
    summary="Get role",
    description="Get role by ID.",
)
def get_role(
    request: Request,
    role_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get role by ID. Requires ROLES_READ permission."""
    return RoleController.get(request, role_id, db)


@router.patch(
    "/{role_id}",
    dependencies=[require_permission(ROLES_UPDATE)],
    summary="Update role",
    description=(
        "Update role details. Builtin roles cannot be modified — attempting "
        "to PATCH one returns 403 forbidden."
    ),
)
def update_role(
    request: Request,
    role_id: int,
    data: RoleUpdateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Update role details. Requires ROLES_UPDATE permission."""
    return RoleController.update(request, role_id, data, db)


@router.delete(
    "/{role_id}",
    dependencies=[require_permission(ROLES_DELETE)],
    summary="Delete role",
    description=(
        "Delete a role. Builtin roles cannot be deleted — attempting to "
        "DELETE one returns 403 forbidden."
    ),
)
def delete_role(
    request: Request,
    role_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a role. Requires ROLES_DELETE permission."""
    return RoleController.delete(request, role_id, db)
