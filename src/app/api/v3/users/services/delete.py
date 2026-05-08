"""
User soft-delete service.

Sets ``deleted_at``, ``deleted_by``, and ``status='inactive'``. The
project_members mapping rows are intentionally NOT removed — undelete
(via PATCH status='active') restores the user with their full mapping
history. Closed/completed projects are filtered out at response time.

Two protection guards are enforced here so the API surface can
never lock the system out of itself:

  - **Self-delete is forbidden.** A logged-in user cannot delete
    their own account (would also revoke their session). Returns
    ``authorization_error`` (403).
  - **Last active super_admin is protected** (doc 42b). Deleting a
    super_admin row is refused if no OTHER active super_admin would
    remain. Returns ``validation_error`` (422) with a message telling
    the caller to promote another user to super_admin first. The
    admin role is NOT lockout-protected anymore — admin is no longer
    the top tier; super_admin is.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def delete_user(
    db: Session,
    user_id: str,
    *,
    actor_id: Optional[str] = None,
) -> ServiceResult[bool]:
    """Soft-delete a user. Idempotent on already-deleted rows."""
    repository = UserRepository(db)

    # Use include_deleted so re-deleting a soft-deleted row reports
    # "already deleted" rather than 404.
    user = repository.get_by_id(user_id, include_deleted=True)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found",
            error_type="not_found",
        )

    # Guard 1: Self-delete is forbidden.
    if actor_id is not None and actor_id == user_id:
        return ServiceResult.fail(
            error="Cannot delete your own account.",
            error_type="authorization_error",
        )

    # Guard 2 (doc 42b): Last-active-super_admin protection. Only fires
    # when the target is an active super_admin — re-deleting an
    # already-deleted user is a no-op (idempotent), so we skip the
    # check on tombstoned rows. admin is no longer the protected tier
    # — admin can be freely deleted as long as a super_admin remains.
    if user.is_super_admin and not user.is_deleted():
        if not repository.has_other_active_super_admin(exclude_user_id=user_id):
            return ServiceResult.fail(
                error=(
                    "Cannot delete the last active super_admin. Promote "
                    "another user to super_admin first."
                ),
                error_type="validation_error",
            )

    try:
        ok = repository.soft_delete(user_id, actor_id=actor_id)
        if not ok:
            return ServiceResult.fail(
                error=f"Failed to delete user with ID {user_id}",
                error_type="internal_error",
            )
        db.commit()
        return ServiceResult.ok(True)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to delete user: {e}",
            error_type="internal_error",
        )
