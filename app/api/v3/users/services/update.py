"""User update + password update services — ported from the monolith."""
from typing import Optional

from sqlalchemy.orm import Session

from .....core.security import hash_password
from .....domain.users.user import User
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult
from .....shared.utils import is_valid_email, is_valid_password, normalize_email


def update_user(
    db: Session,
    user_id: int,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    admin: Optional[bool] = None,
    status: Optional[str] = None,
    requesting_user_id: Optional[int] = None,
    is_admin: bool = False,
) -> ServiceResult[User]:
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found", error_type="not_found",
        )

    is_self = requesting_user_id == user_id

    if admin is not None and not is_admin:
        return ServiceResult.fail(
            error="Only admin users can modify admin flag",
            error_type="authorization_error",
        )
    if status is not None and not is_admin:
        return ServiceResult.fail(
            error="Only admin users can modify user status",
            error_type="authorization_error",
        )
    if not is_admin and not is_self:
        return ServiceResult.fail(
            error="You can only update your own profile",
            error_type="authorization_error",
        )

    if email is not None:
        email = normalize_email(email)
        if not is_valid_email(email):
            return ServiceResult.fail(
                error="Invalid email format", error_type="validation_error",
            )
        existing = repo.get_by_email(email)
        if existing and existing.id != user_id:
            return ServiceResult.fail(
                error=f"Email '{email}' is already in use",
                error_type="already_exists",
            )

    if status is not None and status not in ["active", "locked", "registered"]:
        return ServiceResult.fail(
            error="Invalid status. Must be: active, locked, or registered",
            error_type="validation_error",
        )

    try:
        updated = repo.update(
            user_id=user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            admin=admin,
            status=status,
        )
        if not updated:
            return ServiceResult.fail(
                error=f"Failed to update user with ID {user_id}",
                error_type="internal_error",
            )
        return ServiceResult.ok(updated)
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to update user: {e}", error_type="internal_error",
        )


def update_password(
    db: Session,
    user_id: int,
    new_password: str,
    requesting_user_id: Optional[int] = None,
    is_admin: bool = False,
) -> ServiceResult[bool]:
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found", error_type="not_found",
        )

    is_self = requesting_user_id == user_id
    if not is_admin and not is_self:
        return ServiceResult.fail(
            error="You can only update your own password",
            error_type="authorization_error",
        )

    if not is_valid_password(new_password):
        return ServiceResult.fail(
            error="Password must be at least 8 characters long",
            error_type="validation_error",
        )

    try:
        if not repo.update_password(user_id, hash_password(new_password)):
            return ServiceResult.fail(
                error=f"Failed to update password for user with ID {user_id}",
                error_type="internal_error",
            )
        return ServiceResult.ok(True)
    except Exception as e:
        return ServiceResult.fail(
            error=f"Failed to update password: {e}", error_type="internal_error",
        )
