"""User deletion service — ported from the monolith.

Note: hard delete. Soft-delete could be added later; kept identical to
the monolith for Phase 1 parity.
"""
from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def delete_user(db: Session, user_id: int) -> ServiceResult[bool]:
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found", error_type="not_found",
        )
    try:
        if not repo.delete(user_id):
            return ServiceResult.fail(
                error=f"Failed to delete user with ID {user_id}",
                error_type="internal_error",
            )
        return ServiceResult.ok(True)
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to delete user: {e}", error_type="internal_error",
        )
