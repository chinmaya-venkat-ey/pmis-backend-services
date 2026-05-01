"""Role retrieval service."""
from sqlalchemy.orm import Session

from .....domain.roles.role import Role
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


def get_role_by_id(db: Session, role_id: int) -> ServiceResult[Role]:
    repository = RoleRepository(db)
    role = repository.get_by_id(role_id)
    if not role:
        return ServiceResult.fail(
            error=f"Role with ID {role_id} not found",
            error_type="not_found",
        )
    return ServiceResult.ok(role)


def get_role_by_name(db: Session, name: str) -> ServiceResult[Role]:
    repository = RoleRepository(db)
    role = repository.get_by_name(name)
    if not role:
        return ServiceResult.fail(
            error=f"Role with name '{name}' not found",
            error_type="not_found",
        )
    return ServiceResult.ok(role)
