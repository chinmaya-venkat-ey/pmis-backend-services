"""RefreshService — rotate access + refresh tokens.

Grace window: if the caller's refresh_jti matches `user.previous_refresh_token_jti`
AND the grace deadline hasn't passed, accept it (handles in-flight tokens during
network partitions). Otherwise require the current `refresh_token_jti`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import RefreshTokenInvalidError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
)
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RefreshResponse, TokenPair


class RefreshService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)

    def refresh(self, refresh_token: str) -> RefreshResponse:
        claims = verify_refresh_token(refresh_token)
        if claims is None:
            raise RefreshTokenInvalidError("Refresh token invalid or expired")

        jti = claims.get("jti")
        user_id = claims.get("user_id") or claims.get("sub")
        if not jti or not user_id:
            raise RefreshTokenInvalidError("Refresh token missing required claims")

        # Look up by jti — accepts either current or grace-window jti.
        user = self.user_repo.get_by_refresh_token_jti(jti)
        if user is None:
            raise RefreshTokenInvalidError("Refresh token not recognized")
        if user.deleted_at is not None or user.status != "active":
            raise RefreshTokenInvalidError("Account is not active")

        new_claims = {
            "sub": user.login,
            "user_id": user.id,
            "email": user.email,
        }
        access_token = create_access_token(new_claims)
        new_refresh_token, new_jti, new_refresh_expires = create_refresh_token(new_claims)

        # Rotate: current jti → previous slot with grace window; new jti → current
        self.user_repo.rotate_refresh_token(
            user,
            new_jti=new_jti,
            grace_seconds=settings.refresh_token_grace_seconds,
        )
        self.db.commit()

        _, _, access_payload = verify_access_token(access_token)
        access_exp = access_payload["exp"] if access_payload else None
        access_expires_at = (
            datetime.fromtimestamp(access_exp, tz=timezone.utc)
            if access_exp else datetime.now(timezone.utc)
        )

        return RefreshResponse(
            tokens=TokenPair(
                access_token=access_token,
                refresh_token=new_refresh_token,
                token_type="Bearer",
                access_token_expires_at=access_expires_at,
                refresh_token_expires_at=new_refresh_expires,
            ),
        )
