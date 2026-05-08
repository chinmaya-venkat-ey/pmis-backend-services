"""Resource-type catalog routes (LEGACY — superseded by doc 20).

- GET  /api/v3/resource_types         : list active types (any authenticated user)
- POST /api/v3/resource_types/create  : create a type (admin only)

Both endpoints continue to work but stamp a ``Deprecation: true`` header
pointing at ``/api/v3/master/resource_types``. The FE should migrate; the
new master-data router supports full CRUD (PATCH / DELETE / restore)
which this legacy router never gained.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ....core.base_controller import BaseController
from ....core.errors import AlreadyExistsError
from ....core.middleware.rbac import require_permission
from ....core.rbac import Permission
from ....infrastructure.db.repositories.resource_type_repository import ResourceTypeRepository
from ....infrastructure.db.session import get_db


router = APIRouter(prefix="/resource_types", tags=["resource_types"])


class ResourceTypeCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    code: str = Field(..., min_length=1, max_length=50, description="Canonical lowercase code")
    name: str = Field(..., min_length=1, max_length=255)
    active: bool = Field(True)


def _rt_to_response(rt) -> Dict[str, Any]:
    d = rt.to_dict()
    return {
        "_type": "ResourceType",
        "id": d["id"],
        "code": d["code"],
        "name": d["name"],
        "active": d.get("active", True),
        "createdAt": d.get("created_at"),
        "updatedAt": d.get("updated_at"),
    }


@router.get(
    "",
    dependencies=[require_permission(Permission.RESOURCE_TYPES_READ)],
    summary="List active resource types",
)
def list_resource_types(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    repo = ResourceTypeRepository(db)
    items = [_rt_to_response(rt) for rt in repo.list_active()]
    return BaseController.stamp_deprecation(
        BaseController.ok(data={
            "_type": "Collection",
            "total": len(items),
            "count": len(items),
            "_embedded": {"elements": items},
        }),
        successor_path="/api/v3/master/resource_types",
    )


@router.post(
    "/create",
    dependencies=[require_permission(Permission.RESOURCE_TYPES_MANAGE)],
    summary="Create a resource type (admin)",
    status_code=201,
)
def create_resource_type(
    request: Request,
    data: ResourceTypeCreateRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    repo = ResourceTypeRepository(db)
    if repo.exists_by_code(data.code):
        raise AlreadyExistsError(f"A resource type with code '{data.code.lower()}' already exists.")
    rt = repo.create(code=data.code, name=data.name, active=data.active)
    db.commit()
    return BaseController.stamp_deprecation(
        BaseController.created(data=_rt_to_response(rt)),
        successor_path="/api/v3/master/resource_types/create",
    )
