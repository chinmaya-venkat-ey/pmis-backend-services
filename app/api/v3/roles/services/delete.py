"""Role deletion service.

Doc 21 part B: only the seeded ``admin`` role is fully protected.
Other built-in roles (``member``, ``viewer``) and any custom roles are
deletable. Cascade: dropping a role removes its role_permissions and
user_roles rows so no foreign-key orphans are left behind.
"""
from sqlalchemy.orm import Session

from .....core.permissions import ADMIN_ROLE_NAME
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


def delete_role(db: Session, role_id: int) -> ServiceResult[None]:
    repository = RoleRepository(db)
    role = repository.get_by_id(role_id)
    if not role:
        return ServiceResult.fail(
            error=f"Role with ID {role_id} not found",
            error_type="not_found",
        )
    if role.name == ADMIN_ROLE_NAME:
        return ServiceResult.fail(
            error="The built-in 'admin' role cannot be deleted.",
            error_type="forbidden",
        )
    try:
        success = repository.delete(role_id)
        if success:
            return ServiceResult.ok(None)
        return ServiceResult.fail(
            error=f"Failed to delete role with ID {role_id}",
            error_type="database_error",
        )
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to delete role: {str(e)}",
            error_type="database_error",
        )
