"""Hard-logout service — ported from the monolith.

Two server-side actions per logout:
1. Access token blacklist: the request's access token ``jti`` is inserted
   into ``revoked_tokens``. Every subsequent request carrying that token
   is rejected by the auth middleware.
2. Refresh token revocation: the user row's ``refresh_token_jti`` is
   cleared, so the introspect/refresh flow can no longer mint new tokens.

Idempotent. Re-revoking the same jti is a silent no-op.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .....infrastructure.db.repositories.revoked_token_repository import (
    RevokedTokenRepository,
)
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.service_result import ServiceResult


def logout_user(
    db: Session,
    *,
    user_id: int,
    token_jti: Optional[str],
    token_exp: Optional[datetime],
) -> ServiceResult[dict]:
    # Clear refresh-token metadata (both columns).
    UserRepository(db).update_refresh_token_metadata(user_id, None, None)

    # Blacklist the access token (skip gracefully if jti/exp absent).
    if token_jti and token_exp is not None:
        if token_exp > datetime.now(timezone.utc):
            RevokedTokenRepository(db).revoke(
                jti=token_jti, expires_at=token_exp, user_id=user_id,
            )

    db.commit()
    return ServiceResult.ok({"message": "Logged out successfully."})
