"""Role deletion service."""
from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


def delete_role(db: Session, role_id: int) -> ServiceResult[None]:
    """Delete a role. Builtin roles cannot be deleted."""
    repository = RoleRepository(db)

    role = repository.get_by_id(role_id)
    if not role:
        return ServiceResult.fail(
            error=f"Role with ID {role_id} not found",
            error_type="not_found",
        )

    if role.builtin:
        return ServiceResult.fail(
            error="Cannot delete builtin roles",
            error_type="forbidden",
        )

    try:
        if repository.delete(role_id):
            return ServiceResult.ok(None)
        return ServiceResult.fail(
            error=f"Failed to delete role with ID {role_id}",
            error_type="internal_error",
        )
    except Exception as e:  # noqa: BLE001
        return ServiceResult.fail(
            error=f"Failed to delete role: {e}",
            error_type="internal_error",
        )
