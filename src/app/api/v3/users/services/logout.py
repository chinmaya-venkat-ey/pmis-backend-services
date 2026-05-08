"""
Logout — hard revocation (Option B).

Two server-side actions per logout call:

1. **Access token blacklist** — the current request's access token ``jti``
   is inserted into ``RevokedTokenModel`` with the token's natural
   ``expires_at``. Auth middleware checks this on every subsequent
   request; the revoked token is rejected immediately, even before its
   exp time. Idempotent: re-revoking a jti is a silent no-op.

2. **Refresh token revocation** — the user's stored ``refresh_token_jti``
   on ``users`` is cleared. Any subsequent ``/users/introspect`` call
   carrying that refresh token will fail with 401 ("invalid or reused").

Together these guarantee:
- The just-used access token can no longer authenticate.
- The user's refresh token can no longer mint new access tokens.
- The user must log in again to get a working session.

Tokens issued elsewhere (e.g. the user has another browser open) are NOT
affected by this call. Each token has its own jti; only the one carried
in the logout request gets blacklisted. This matches the typical "logout
on this device" UX. A future "logout everywhere" endpoint would walk every
unexpired access token for the user (not in scope today).
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
    user_id: str,
    token_jti: Optional[str],
    token_exp: Optional[datetime],
) -> ServiceResult[dict]:
    """
    Revoke the current request's access token (by jti) and clear the
    user's refresh token. Idempotent.

    Args:
        db: Database session.
        user_id: From the authenticated request (request.state.user_id).
        token_jti: From the authenticated request (request.state.token_jti).
            May be None for tokens issued before the jti claim landed; in
            that case access-token blacklisting is skipped (the token
            expires naturally) but refresh-token revocation still happens.
        token_exp: From the authenticated request (request.state.token_exp).
            UTC datetime of the token's natural expiry.

    Returns:
        ServiceResult.ok({"message": "..."}) on success. Always succeeds
        if the user exists; idempotent otherwise.
    """
    # Refresh-token revocation. Clears the live jti, expiry, AND any
    # in-flight grace-window columns on the user row so neither the
    # current refresh token nor the just-rotated-out one can mint
    # further pairs. Logout is an explicit "stop my session now" — no
    # grace period after.
    user_repo = UserRepository(db)
    user_repo.rotate_refresh_token(user_id, None, None, grace_seconds=0)

    # Access-token blacklisting (skip gracefully if jti is missing).
    if token_jti and token_exp is not None:
        # Defensive: if the token has somehow already expired, no point
        # writing a row that will never gate anything.
        if token_exp > datetime.now(timezone.utc):
            RevokedTokenRepository(db).revoke(
                jti=token_jti,
                expires_at=token_exp,
                user_id=user_id,
            )

    db.commit()
    return ServiceResult.ok({"message": "Logged out successfully."})
