"""User retrieval services — ported from the monolith."""
from typing import Optional

from sqlalchemy.orm import Session

from .....domain.users.user import User
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def get_user_by_id(
    db: Session,
    user_id: int,
    requesting_user_id: Optional[int] = None,
    is_admin: bool = False,
) -> ServiceResult[User]:
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if not user:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found", error_type="not_found",
        )

    # Non-admin can only see active users (unless it's themselves)
    if not is_admin and user.status != "active" and user_id != requesting_user_id:
        return ServiceResult.fail(
            error=f"User with ID {user_id} not found", error_type="not_found",
        )

    return ServiceResult.ok(user)


def get_user_by_login(db: Session, login: str) -> ServiceResult[User]:
    repo = UserRepository(db)
    user = repo.get_by_login(login)
    if not user:
        return ServiceResult.fail(
            error=f"User with login '{login}' not found", error_type="not_found",
        )
    return ServiceResult.ok(user)
