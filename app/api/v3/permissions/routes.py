"""Permission catalog endpoints (doc 21 part B).

CRUD on the ``permissions`` table. Built-in permission rows (those
synced from ``app/core/permissions.py`` at startup) cannot be deleted —
only their name and description may be edited. Custom rows can be edited
or deleted freely.
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.middleware.rbac import require_permission
from ....core.permissions import (
    PERMISSIONS_MANAGE,
    PERMISSIONS_READ,
)
from ....core.response import format_error_response
from ....infrastructure.db.repositories.rbac_repository import RbacRepository
from ....infrastructure.db.session import get_db
from ....shared.datetime import iso_ist
from .schemas import PermissionCreateRequest, PermissionUpdateRequest


router = APIRouter(prefix="/permissions", tags=["permissions"])


def _stamp(resp, *, successor: str):
    """Stamp Deprecation + Link headers pointing at the master successor.

    Doc 21B follow-up: permission catalog CRUD now lives under
    ``/api/v3/master/permissions/*``. Legacy paths keep working during
    the FE migration window.
    """
    return BaseController.stamp_deprecation(resp, successor_path=successor)


def _serialize(p) -> Dict[str, Any]:
    return {
        "_type": "Permission",
        "_links": {"self": {"href": f"/api/v3/permissions/{p.code}"}},
        "code": p.code,
        "name": p.name,
        "description": p.description,
        "isBuiltin": p.is_builtin,
        "createdAt": iso_ist(p.created_at),
        "updatedAt": iso_ist(p.updated_at),
    }


@router.get(
    "",
    dependencies=[require_permission(PERMISSIONS_READ)],
    summary=(
        "List permission catalog "
        "(DEPRECATED — use GET /api/v3/master/permissions)"
    ),
)
def list_permissions(
    request: Request,
    offset: int = Query(1, ge=1),
    pageSize: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = RbacRepository(db)
    rows, total = repo.list_permissions(
        offset=(offset - 1) * pageSize, limit=pageSize,
    )
    payload = {
        "_type": "Collection",
        "_links": {"self": {"href": f"/api/v3/master/permissions?offset={offset}&pageSize={pageSize}"}},
        "total": total,
        "count": len(rows),
        "pageSize": pageSize,
        "offset": offset,
        "_embedded": {"elements": [_serialize(r) for r in rows]},
    }
    return _stamp(
        BaseController.ok(data=payload),
        successor="/api/v3/master/permissions",
    )


@router.get(
    "/{code}",
    dependencies=[require_permission(PERMISSIONS_READ)],
    summary=(
        "Get a permission row "
        "(DEPRECATED — use GET /api/v3/master/permissions/{code})"
    ),
)
def get_permission(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    successor = f"/api/v3/master/permissions/{code}"
    row = RbacRepository(db).get_permission(code)
    if row is None:
        return _stamp(
            BaseController.error(
                format_error_response("not_found", f"Permission {code} not found."),
                status=404,
            ),
            successor=successor,
        )
    return _stamp(BaseController.ok(data=_serialize(row)), successor=successor)


@router.post(
    "",
    dependencies=[require_permission(PERMISSIONS_MANAGE)],
    summary=(
        "Create a custom permission "
        "(DEPRECATED — use POST /api/v3/master/permissions/create)"
    ),
    status_code=201,
)
def create_permission(
    request: Request,
    data: PermissionCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    successor = "/api/v3/master/permissions/create"
    repo = RbacRepository(db)
    if repo.get_permission(data.code) is not None:
        return _stamp(
            BaseController.error(
                format_error_response(
                    "already_exists", f"Permission {data.code} already exists.",
                ),
                status=409,
            ),
            successor=successor,
        )
    row = repo.create_permission(
        code=data.code, name=data.name, description=data.description,
        is_builtin=False,
    )
    db.commit()
    return _stamp(BaseController.created(data=_serialize(row)), successor=successor)


@router.patch(
    "/{code}",
    dependencies=[require_permission(PERMISSIONS_MANAGE)],
    summary=(
        "Edit name/description of a permission "
        "(DEPRECATED — use PATCH /api/v3/master/permissions/{code})"
    ),
)
def update_permission(
    request: Request, code: str,
    data: PermissionUpdateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    successor = f"/api/v3/master/permissions/{code}"
    repo = RbacRepository(db)
    row = repo.update_permission(
        code, name=data.name, description=data.description,
    )
    if row is None:
        return _stamp(
            BaseController.error(
                format_error_response("not_found", f"Permission {code} not found."),
                status=404,
            ),
            successor=successor,
        )
    db.commit()
    return _stamp(BaseController.ok(data=_serialize(row)), successor=successor)


@router.delete(
    "/{code}",
    dependencies=[require_permission(PERMISSIONS_MANAGE)],
    summary=(
        "Delete a permission "
        "(DEPRECATED — use DELETE /api/v3/master/permissions/{code})"
    ),
)
def delete_permission(
    request: Request, code: str, db: Session = Depends(get_db),
) -> JSONResponse:
    successor = f"/api/v3/master/permissions/{code}"
    repo = RbacRepository(db)
    row = repo.get_permission(code)
    if row is None:
        return _stamp(
            BaseController.error(
                format_error_response("not_found", f"Permission {code} not found."),
                status=404,
            ),
            successor=successor,
        )
    if row.is_builtin:
        return _stamp(
            BaseController.error(
                format_error_response(
                    "forbidden",
                    f"Permission {code} is built-in and cannot be deleted.",
                ),
                status=403,
            ),
            successor=successor,
        )
    repo.delete_permission(code)
    db.commit()
    return _stamp(BaseController.no_content(), successor=successor)
