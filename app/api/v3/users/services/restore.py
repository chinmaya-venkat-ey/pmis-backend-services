"""
Dedicated user-restore service.

Mirrors the ``POST /vendors/{id}/restore`` pattern kamal added on the
vendor side, so the API surface is symmetric: every resource that has
a soft-DELETE has an explicit POST /<id>/restore counterpart. The
PATCH ``{status: "active"}`` path on a soft-deleted user remains
supported (it falls through to ``update.py``); both paths converge on
the same ``UserRepository.update(restore=True)`` call.

Idempotent: calling restore on an already-active user returns the
current snapshot with HTTP 200 rather than 409. Treating it as a
benign retry matches the vendor restore behaviour and keeps the
frontend simple.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....domain.users.user import User
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def restore_user(
    db: Session,
    user_id: str,
    *,
    requesting_user_id: Optional[str] = None,
    is_admin: bool = False,
) -> ServiceResult[User]:
    """Clear soft-delete flags + set status='active' on a user.

    Requires admin. Idempotent on already-active users.
    """
    if not is_admin:
        return ServiceResult.fail(
            error="Only admin users can restore users.",
            error_type="authorization_error",
        )

    repository = UserRepository(db)

    user = repository.get_by_id(user_id, include_deleted=True)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found",
            error_type="not_found",
        )

    # Idempotent path: not currently soft-deleted → return current state
    # without touching the row. Avoids a spurious updated_at bump on
    # benign retries from the FE.
    if not user.is_deleted():
        return ServiceResult.ok(user)

    try:
        updated = repository.update(
            user_id=user_id,
            status="active",
            restore=True,
        )
        if not updated:
            return ServiceResult.fail(
                error=f"Failed to restore user with ID {user_id}",
                error_type="internal_error",
            )
        db.commit()
        return ServiceResult.ok(updated)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to restore user: {e}",
            error_type="internal_error",
        )
