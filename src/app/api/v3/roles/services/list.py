"""
Role list service.
"""
from typing import Tuple, List
from sqlalchemy.orm import Session
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....domain.roles.role import Role
from .....shared.service_result import ServiceResult


def list_roles(
    db: Session,
    offset: int = 0,
    limit: int = 20
) -> ServiceResult[Tuple[List[Role], int]]:
    """
    List roles with pagination.

    Args:
        db: Database session
        offset: Number of items to skip
        limit: Maximum number of items to return

    Returns:
        ServiceResult with list of roles and total count or error
    """
    if offset < 0:
        return ServiceResult.fail(
            error="Offset must be >= 0",
            error_type="validation_error"
        )

    if limit < 1 or limit > 100:
        return ServiceResult.fail(
            error="Limit must be between 1 and 100",
            error_type="validation_error"
        )

    try:
        repository = RoleRepository(db)
        roles, total = repository.list(offset=offset, limit=limit)
        return ServiceResult.ok((roles, total))
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to list roles: {str(e)}",
            error_type="database_error"
        )
