"""Routes for the project_categories catalog (doc 37)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status

from app.controllers.project_category_controller import ProjectCategoryController
from app.core.permissions import PROJECT_CATEGORIES_MANAGE, PROJECT_CATEGORIES_READ
from app.core.rbac import require_permission
from app.dependencies import get_project_category_controller
from app.schemas.project_category import (
    ProjectCategoryCreateRequest,
    ProjectCategoryResponse,
    ProjectCategoryUpdateRequest,
)


router = APIRouter(prefix="/project_categories", tags=["project_categories"])


@router.get(
    "",
    summary="List project categories",
    description="Returns project categories used by the project-create form. Requires project_categories:read.",
    dependencies=[Depends(require_permission(PROJECT_CATEGORIES_READ))],
)
def list_project_categories(
    include_inactive: bool = Query(False, description="Include deactivated rows"),
    controller: Annotated[ProjectCategoryController, Depends(get_project_category_controller)] = Depends(get_project_category_controller),
) -> List[ProjectCategoryResponse]:
    return controller.list_(include_inactive=include_inactive)


@router.get(
    "/{code}",
    summary="Get project category details",
    dependencies=[Depends(require_permission(PROJECT_CATEGORIES_READ))],
    responses={404: {"description": "ProjectCategory not found"}},
)
def get_project_category_details(
    code: str,
    controller: Annotated[ProjectCategoryController, Depends(get_project_category_controller)] = Depends(get_project_category_controller),
) -> ProjectCategoryResponse:
    return controller.get_details(code)


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create a project category",
    dependencies=[Depends(require_permission(PROJECT_CATEGORIES_MANAGE))],
    responses={409: {"description": "ProjectCategory code already exists"}},
)
def create_project_category(
    payload: ProjectCategoryCreateRequest,
    controller: Annotated[ProjectCategoryController, Depends(get_project_category_controller)] = Depends(get_project_category_controller),
) -> ProjectCategoryResponse:
    return controller.create(payload)


@router.patch(
    "/{code}",
    summary="Update a project category",
    dependencies=[Depends(require_permission(PROJECT_CATEGORIES_MANAGE))],
    responses={404: {"description": "ProjectCategory not found"}},
)
def update_project_category(
    code: str,
    payload: ProjectCategoryUpdateRequest,
    controller: Annotated[ProjectCategoryController, Depends(get_project_category_controller)] = Depends(get_project_category_controller),
) -> ProjectCategoryResponse:
    return controller.update(code, payload)


@router.delete(
    "/{code}",
    summary="Delete (deactivate) a project category",
    dependencies=[Depends(require_permission(PROJECT_CATEGORIES_MANAGE))],
    responses={404: {"description": "ProjectCategory not found"}},
)
def delete_project_category(
    code: str,
    controller: Annotated[ProjectCategoryController, Depends(get_project_category_controller)] = Depends(get_project_category_controller),
) -> ProjectCategoryResponse:
    return controller.delete(code)


@router.post(
    "/{code}/restore",
    summary="Restore (reactivate) a project category",
    dependencies=[Depends(require_permission(PROJECT_CATEGORIES_MANAGE))],
    responses={404: {"description": "ProjectCategory not found"}},
)
def restore_project_category(
    code: str,
    controller: Annotated[ProjectCategoryController, Depends(get_project_category_controller)] = Depends(get_project_category_controller),
) -> ProjectCategoryResponse:
    return controller.restore(code)
