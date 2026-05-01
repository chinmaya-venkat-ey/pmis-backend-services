"""Role update service."""
from typing import List, Optional

from sqlalchemy.orm import Session

from .....domain.roles.role import Role
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


def update_role(
    db: Session,
    role_id: int,
    name: Optional[str] = None,
    permissions: Optional[List[str]] = None,
) -> ServiceResult[Role]:
    """Update a role. Builtin roles cannot be modified."""
    repository = RoleRepository(db)

    role = repository.get_by_id(role_id)
    if not role:
        return ServiceResult.fail(
            error=f"Role with ID {role_id} not found",
            error_type="not_found",
        )

    if role.builtin:
        return ServiceResult.fail(
            error="Cannot modify builtin roles",
            error_type="forbidden",
        )

    if name is not None:
        if not isinstance(name, str) or len(name) == 0:
            return ServiceResult.fail(
                error="Role name must be a non-empty string",
                error_type="validation_error",
            )
        if len(name) > 255:
            return ServiceResult.fail(
                error="Role name must not exceed 255 characters",
                error_type="validation_error",
            )
        existing = repository.get_by_name(name)
        if existing and existing.id != role_id:
            return ServiceResult.fail(
                error=f"Role with name '{name}' already exists",
                error_type="already_exists",
            )

    if permissions is not None and not isinstance(permissions, list):
        return ServiceResult.fail(
            error="Permissions must be a list",
            error_type="validation_error",
        )

    try:
        updated = repository.update(
            role_id=role_id, name=name, permissions=permissions,
        )
        return ServiceResult.ok(updated)
    except Exception as e:  # noqa: BLE001
        return ServiceResult.fail(
            error=f"Failed to update role: {e}",
            error_type="internal_error",
        )
