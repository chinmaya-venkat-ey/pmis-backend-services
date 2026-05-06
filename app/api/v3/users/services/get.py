"""
User retrieval service.
"""
from typing import Optional
from sqlalchemy.orm import Session
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....domain.users.user import User
from .....shared.service_result import ServiceResult


def get_user_by_id(
    db: Session,
    user_id: str,
    requesting_user_id: Optional[str] = None,
    is_admin: bool = False
) -> ServiceResult[User]:
    """
    Get user by ID.

    Args:
        db: Database session
        user_id: User ID to retrieve
        requesting_user_id: ID of user making the request
        is_admin: Whether requesting user is admin

    Returns:
        ServiceResult with user or error
    """
    repository = UserRepository(db)

    user = repository.get_by_id(user_id)

    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found",
            error_type="not_found"
        )

    # Non-admin users can only view active users (unless viewing themselves)
    if not is_admin and user.status != "active" and user_id != requesting_user_id:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found",
            error_type="not_found"
        )

    return ServiceResult.ok(user)


def get_user_by_login(
    db: Session,
    login: str
) -> ServiceResult[User]:
    """
    Get user by login.

    Args:
        db: Database session
        login: User login

    Returns:
        ServiceResult with user or error
    """
    repository = UserRepository(db)

    user = repository.get_by_login(login)

    if not user:
        return ServiceResult.fail(
            error=f"User with login '{login}' not found",
            error_type="not_found"
        )

    return ServiceResult.ok(user)
