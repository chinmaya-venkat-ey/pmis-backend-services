"""
Role creation service.
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from .....core.errors import ValidationError
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....domain.roles.role import Role
from .....shared.service_result import ServiceResult


def create_role(
    db: Session,
    name: str,
    permissions: List[str],
    builtin: bool = False,
    description: Optional[str] = None,
) -> ServiceResult[Role]:
    """
    Create a new role.

    Args:
        db: Database session
        name: Role name
        permissions: List of permissions
        builtin: Whether role is builtin

    Returns:
        ServiceResult with created role or error
    """
    # Validate inputs
    if not name or not isinstance(name, str):
        return ServiceResult.fail(
            error="Role name is required and must be a string",
            error_type="validation_error"
        )

    if len(name) < 1 or len(name) > 255:
        return ServiceResult.fail(
            error="Role name must be between 1 and 255 characters",
            error_type="validation_error"
        )

    if not isinstance(permissions, list):
        return ServiceResult.fail(
            error="Permissions must be a list",
            error_type="validation_error"
        )

    # Check for existing role
    repository = RoleRepository(db)

    if repository.exists_by_name(name):
        return ServiceResult.fail(
            error=f"Role with name '{name}' already exists",
            error_type="already_exists"
        )

    # Create the role
    try:
        role = repository.create(
            name=name,
            permissions=permissions,
            builtin=builtin,
            description=description,
        )
        return ServiceResult.ok(role)
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to create role: {str(e)}",
            error_type="database_error"
        )
