"""Role creation service."""
from typing import List

from sqlalchemy.orm import Session

from .....domain.roles.role import Role
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


def create_role(
    db: Session,
    name: str,
    permissions: List[str],
    builtin: bool = False,
) -> ServiceResult[Role]:
    """Create a new role."""
    if not name or not isinstance(name, str):
        return ServiceResult.fail(
            error="Role name is required and must be a string",
            error_type="validation_error",
        )
    if len(name) < 1 or len(name) > 255:
        return ServiceResult.fail(
            error="Role name must be between 1 and 255 characters",
            error_type="validation_error",
        )
    if not isinstance(permissions, list):
        return ServiceResult.fail(
            error="Permissions must be a list",
            error_type="validation_error",
        )

    repository = RoleRepository(db)

    if repository.exists_by_name(name):
        return ServiceResult.fail(
            error=f"Role with name '{name}' already exists",
            error_type="already_exists",
        )

    try:
        role = repository.create(
            name=name, permissions=permissions, builtin=builtin,
        )
        return ServiceResult.ok(role)
    except Exception as e:  # noqa: BLE001
        return ServiceResult.fail(
            error=f"Failed to create role: {e}",
            error_type="internal_error",
        )
