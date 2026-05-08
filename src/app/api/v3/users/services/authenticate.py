"""
User authentication service.

Doc 21 part B: JWT no longer carries ``role`` or ``is_admin`` claims.
Effective permissions and admin status are looked up per-request from
the DB by the auth middleware. The token payload is the minimum needed
to identify the caller — sub, user_id, email, jti, exp.
"""
from sqlalchemy.orm import Session
from .....core.security import verify_password, create_access_token, create_refresh_token
from .....core.config import settings
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def authenticate_user(
    db: Session,
    login: str,
    password: str
) -> ServiceResult[dict]:
    repository = UserRepository(db)

    user = repository.get_by_login(login)
    if not user:
        return ServiceResult.fail(
            error="Invalid credentials",
            error_type="invalid_credentials"
        )

    if user.status != "active":
        return ServiceResult.fail(
            error="User account is not active",
            error_type="authentication_error"
        )

    password_hash = repository.get_password_hash_by_login(login)
    if not password_hash or not verify_password(password, password_hash):
        return ServiceResult.fail(
            error="Invalid credentials",
            error_type="invalid_credentials"
        )

    token_data = {
        "sub": user.login,
        "user_id": user.id,
        "email": user.email,
    }

    access_token = create_access_token(token_data)
    refresh_token, refresh_jti, refresh_expires = create_refresh_token({
        "sub": user.login,
        "user_id": user.id,
        "email": user.email,
    })

    # Rotate the user's refresh-token jti. ``grace_seconds`` keeps the
    # previously-issued refresh token valid for a short window so a parallel
    # tab / login replay / in-flight refresh from before this login still
    # resolves successfully. See settings.REFRESH_TOKEN_GRACE_SECONDS and
    # the user-repository docstring for details.
    repository.rotate_refresh_token(
        user.id, refresh_jti, refresh_expires,
        grace_seconds=settings.REFRESH_TOKEN_GRACE_SECONDS,
    )

    return ServiceResult.ok({
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "user": user
    })
