"""Role deletion service.

The seeded ``admin`` and ``super_admin`` roles are fully protected
from deletion. Other built-in roles (``member``, ``viewer``,
``vendor``, ``org_admin``, ``project_admin``, ``project_member``,
``division_member``) and any custom roles are deletable. Cascade:
dropping a role removes its role_permissions and user_roles rows so
no foreign-key orphans are left behind.
"""
from sqlalchemy.orm import Session

from .....core.permissions import (
    ADMIN_ROLE_NAME, SUPER_ADMIN_ROLE_NAME,
)
from .....infrastructure.db.repositories.role_repository import RoleRepository
from .....shared.service_result import ServiceResult


# Roles that can never be deleted via the API. The list is hard-coded
# here (rather than read from `roles.builtin = True`) because some
# built-in roles like `member`/`viewer` are admin-customisable and
# may be deleted by an operator who chooses not to use them.
_UNDELETABLE_ROLES = frozenset({ADMIN_ROLE_NAME, SUPER_ADMIN_ROLE_NAME})


def delete_role(db: Session, role_id: int) -> ServiceResult[None]:
    repository = RoleRepository(db)
    role = repository.get_by_id(role_id)
    if not role:
        return ServiceResult.fail(
            error=f"Role with ID {role_id} not found",
            error_type="not_found",
        )
    if role.name in _UNDELETABLE_ROLES:
        return ServiceResult.fail(
            error=f"The built-in '{role.name}' role cannot be deleted.",
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
