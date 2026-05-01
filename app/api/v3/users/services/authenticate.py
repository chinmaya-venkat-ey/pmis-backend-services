"""Authentication service — login flow. Ported from the monolith."""
from sqlalchemy.orm import Session

from .....core.config import settings
from .....core.rbac import Role
from .....core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def authenticate_user(db: Session, login: str, password: str) -> ServiceResult[dict]:
    """Verify credentials, mint access + refresh tokens, persist refresh
    metadata on the user row. Returns tokens + user domain object.
    """
    repo = UserRepository(db)

    user = repo.get_by_login(login)
    if not user:
        return ServiceResult.fail(
            error="Invalid credentials", error_type="invalid_credentials",
        )

    if user.status != "active":
        return ServiceResult.fail(
            error="User account is not active", error_type="authentication_error",
        )

    password_hash = repo.get_password_hash_by_login(login)
    if not password_hash or not verify_password(password, password_hash):
        return ServiceResult.fail(
            error="Invalid credentials", error_type="invalid_credentials",
        )

    role = Role.ADMIN if user.admin else Role.MEMBER

    token_data = {
        "sub": user.login,
        "user_id": user.id,
        "email": user.email,
        "role": role.value,
        "is_admin": user.admin,
    }

    access_token = create_access_token(token_data)
    refresh_token, refresh_jti, refresh_expires = create_refresh_token(token_data)

    # Rotate the user's refresh-token jti. ``grace_seconds`` keeps the
    # previously-issued refresh token valid for a short window so a
    # parallel tab / login replay / in-flight refresh from before this
    # login still resolves successfully.
    repo.rotate_refresh_token(
        user.id, refresh_jti, refresh_expires,
        grace_seconds=settings.REFRESH_TOKEN_GRACE_SECONDS,
    )

    return ServiceResult.ok({
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "user": user,
    })
