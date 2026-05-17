"""RefreshService — rotate access + refresh tokens.

Grace window: if the caller's refresh_jti matches `user.previous_refresh_token_jti`
AND the grace deadline hasn't passed, accept it (handles in-flight tokens during
network partitions). Otherwise require the current `refresh_token_jti`.

Round-8 wire-shape fix: returns the full monolith-parity envelope including
`user`, `accessTokenIssuedAt`, `refreshTokenIssuedAt`, and `expiresInSeconds`
so FE state-rehydration on refresh works the same as on login.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import RefreshTokenInvalidError
from app.core.permissions import SUPER_ADMIN_ROLE
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
)
from app.models.user_role import UserRole
from app.models.user_role_assignment import UserRoleAssignment
from app.repositories.rbac_repository import RbacRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginUserSummary, RefreshResponse


class RefreshService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.rbac = RbacRepository(db)

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

        # Rotate: current jti -> previous slot with grace window; new jti -> current
        self.user_repo.rotate_refresh_token(
            user,
            new_jti=new_jti,
            grace_seconds=settings.refresh_token_grace_seconds,
        )
        self.db.commit()

        # Pull exp + iat off the freshly-minted access token for the response.
        _, _, access_payload = verify_access_token(access_token)
        access_exp = access_payload.get("exp") if access_payload else None
        access_iat = access_payload.get("iat") if access_payload else None
        now = datetime.now(timezone.utc)
        access_expires_at = (
            datetime.fromtimestamp(access_exp, tz=timezone.utc) if access_exp else now
        )
        access_issued_at = (
            datetime.fromtimestamp(access_iat, tz=timezone.utc) if access_iat else now
        )
        expires_in_seconds = (
            int(access_exp - access_iat) if (access_exp and access_iat) else None
        )

        # Build the user summary (matches LoginResponse.user shape).
        is_admin = self.rbac.user_has_admin_role(user.id)
        perms = sorted(self.rbac.effective_permissions_for_user(user.id))
        is_super = self._is_super_admin(user.id)

        return RefreshResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            access_token_expires_at=access_expires_at,
            access_token_issued_at=access_issued_at,
            refresh_token_expires_at=new_refresh_expires,
            refresh_token_issued_at=now,
            expires_in_seconds=expires_in_seconds,
            user=LoginUserSummary(
                id=user.id,
                login=user.login,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                is_admin=is_admin,
                is_super_admin=is_super,
                permissions=perms,
            ),
        )

    def _is_super_admin(self, user_id: str) -> bool:
        super_role = self.rbac.get_role_by_name(SUPER_ADMIN_ROLE)
        if super_role is None:
            return False
        if self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.user_id == user_id)
            .where(UserRole.role_id == super_role.id)
            .limit(1)
        ).first():
            return True
        return self.db.execute(
            select(UserRoleAssignment.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(UserRoleAssignment.role_id == super_role.id)
            .limit(1)
        ).first() is not None
