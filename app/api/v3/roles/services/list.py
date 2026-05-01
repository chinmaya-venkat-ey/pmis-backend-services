"""Role list service."""
from typing import List, Tuple

from sqlalchemy.orm import Session

from .....domain.roles.role import Role
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


def list_roles(
    db: Session,
    offset: int = 0,
    limit: int = 20,
) -> ServiceResult[Tuple[List[Role], int]]:
    """List roles with pagination."""
    if offset < 0:
        return ServiceResult.fail(
            error="Offset must be >= 0",
            error_type="validation_error",
        )
    if limit < 1 or limit > 100:
        return ServiceResult.fail(
            error="Limit must be between 1 and 100",
            error_type="validation_error",
        )

    try:
        repository = RoleRepository(db)
        roles, total = repository.list(offset=offset, limit=limit)
        return ServiceResult.ok((roles, total))
    except Exception as e:  # noqa: BLE001
        return ServiceResult.fail(
            error=f"Failed to list roles: {e}",
            error_type="internal_error",
        )
