"""Role update service.

Doc 21 part B: only the seeded ``admin`` role is fully locked (cannot be
renamed and cannot have its permission list changed via the management
endpoints — its permission set is auto-maintained by the startup sync).
Other built-in roles can be renamed and edited freely.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from .....core.permissions import ADMIN_ROLE_NAME
from .....domain.roles.role import Role
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


def update_role(
    db: Session,
    role_id: int,
    name: Optional[str] = None,
    permissions: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> ServiceResult[Role]:
    repository = RoleRepository(db)

    role = repository.get_by_id(role_id)
    if not role:
        return ServiceResult.fail(
            error=f"Role with ID {role_id} not found",
            error_type="not_found",
        )

    if role.name == ADMIN_ROLE_NAME:
        return ServiceResult.fail(
            error="The built-in 'admin' role cannot be modified.",
            error_type="forbidden",
        )

    if name is not None:
        if not isinstance(name, str) or len(name) == 0 or len(name) > 255:
            return ServiceResult.fail(
                error="Role name must be a non-empty string ≤ 255 chars",
                error_type="validation_error",
            )
        if name == ADMIN_ROLE_NAME:
            return ServiceResult.fail(
                error="Cannot rename a role to 'admin' (reserved).",
                error_type="forbidden",
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
            description=description,
        )
        return ServiceResult.ok(updated)
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to update role: {str(e)}",
            error_type="database_error",
        )
