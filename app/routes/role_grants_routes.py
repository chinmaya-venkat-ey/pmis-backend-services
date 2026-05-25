"""Routes for /user/role-grants/{role_name}/matrix."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.controllers.role_grants_controller import RoleGrantsController
from app.core.rbac import require_authenticated
from app.dependencies import get_role_grants_controller
from app.schemas.role_grants import RoleGrantsMatrixResponse


router = APIRouter(prefix="/role-grants", tags=["role_grants"])


@router.get(
    "/{role_name}",
    response_model=RoleGrantsMatrixResponse,
    summary="Get the grantable-roles matrix for a role tier",
    description=(
        "Returns which roles a caller holding `role_name` can grant + at "
        "what scope. Static-data matrix encoding Doc-42b rules."
    ),
    dependencies=[Depends(require_authenticated())],
)
def get_role_grants_matrix(
    role_name: str,
    controller: Annotated[RoleGrantsController, Depends(get_role_grants_controller)],
):
    return controller.get_matrix(role_name)
