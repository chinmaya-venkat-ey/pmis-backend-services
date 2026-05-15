"""AuthService — login, logout, introspect, /me.

Login flow:
  1. Look up user (case-sensitive login OR email).
  2. Verify password (argon2). Soft-deleted / inactive users → InvalidCredentials.
  3. If 2FA required (settings.require_2fa OR user.two_factor_enabled):
     create a pending OtpCode row keyed by an ephemeral_token, raise
     TwoFactorRequiredError so the FE can call /login/send-otp + /verify-otp.
  4. Otherwise mint access + refresh tokens, persist refresh_jti, return.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import (
    InvalidCredentialsError,
    TwoFactorRequiredError,
    UserNotFoundError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from app.repositories.otp_code_repository import OtpCodeRepository
from app.repositories.rbac_repository import RbacRepository
from app.repositories.revoked_token_repository import RevokedTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    IntrospectResponse,
    LoginResponse,
    LoginUserSummary,
    LogoutResponse,
    TokenPair,
)
from app.utilities.otp import generate_ephemeral_token, hash_ephemeral_token


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.otp_repo = OtpCodeRepository(db)
        self.rbac = RbacRepository(db)
        self.revoked = RevokedTokenRepository(db)

    # ------------------------------------------------------------------ login

    def authenticate(self, login: str, password: str) -> LoginResponse:
        """Returns LoginResponse on success; raises TwoFactorRequiredError or
        InvalidCredentialsError otherwise."""
        # Treat `login` as either username or email (case-sensitive match
        # on either column matches the monolith convention).
        user = self.user_repo.get_by_login(login) or self.user_repo.get_by_email(login)
        if user is None or user.deleted_at is not None or user.status != "active":
            raise InvalidCredentialsError("Invalid credentials")

        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError("Invalid credentials")

        # 2FA gate
        is_2fa_required = bool(settings.require_2fa or user.two_factor_enabled)
        if is_2fa_required:
            # Issue an ephemeral token tied to this attempt; the FE then
            # calls /login/send-otp with this token to receive the code.
            ephemeral_token = generate_ephemeral_token()
            ephemeral_hash = hash_ephemeral_token(ephemeral_token)
            # Create a pending OtpCode row WITHOUT a code yet; send-otp fills it.
            self.otp_repo.create(
                user_id=user.id,
                channel="email",
                code_hash=None,
                ephemeral_token_hash=ephemeral_hash,
                ttl_seconds=settings.otp_ttl_seconds,
            )
            self.db.commit()
            channels = ["email"]
            if user.phone_number:
                channels.append("sms")
            raise TwoFactorRequiredError(
                "Two-factor authentication required",
                ephemeral_token=ephemeral_token,
                channels_available=channels,
            )

        return self._issue_login(user)

    def _issue_login(self, user) -> LoginResponse:
        """Common path: mint tokens, persist refresh_jti, build LoginResponse."""
        is_admin = self.rbac.user_has_admin_role(user.id)
        is_super = self._is_super_admin(user.id)
        perms = sorted(self.rbac.effective_permissions_for_user(user.id))

        claims = {
            "sub": user.login,
            "user_id": user.id,
            "email": user.email,
        }
        access_token = create_access_token(claims)
        refresh_token, refresh_jti, refresh_expires_at = create_refresh_token(claims)

        # Decode access_token to grab its expiry without re-implementing.
        _, _, access_payload = verify_access_token(access_token)
        access_exp = access_payload["exp"] if access_payload else None
        access_expires_at = (
            datetime.fromtimestamp(access_exp, tz=timezone.utc) if access_exp else _utcnow()
        )

        # Persist new refresh_token_jti and clear any grace-window remnant.
        self.user_repo.rotate_refresh_token(user, new_jti=refresh_jti, grace_seconds=0)
        self.db.commit()

        return LoginResponse(
            tokens=TokenPair(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="Bearer",
                access_token_expires_at=access_expires_at,
                refresh_token_expires_at=refresh_expires_at,
            ),
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
        """Check specifically for `super_admin` role (a subset of is_admin)."""
        from app.core.permissions import SUPER_ADMIN_ROLE

        role = self.rbac.get_role_by_name(SUPER_ADMIN_ROLE)
        if role is None:
            return False
        # Roundabout but cheap: check role-assignment OR legacy user_role
        from sqlalchemy import select
        from app.models.user_role import UserRole
        from app.models.user_role_assignment import UserRoleAssignment

        if self.db.execute(
            select(UserRole.user_id)
            .where(UserRole.user_id == user_id)
            .where(UserRole.role_id == role.id)
            .limit(1)
        ).first():
            return True
        return self.db.execute(
            select(UserRoleAssignment.id)
            .where(UserRoleAssignment.user_id == user_id)
            .where(UserRoleAssignment.role_id == role.id)
            .limit(1)
        ).first() is not None

    # ------------------------------------------------------------------ logout

    def logout(self, *, user_id: str, jti: str) -> LogoutResponse:
        """Revoke the access token's jti AND clear the refresh state."""
        if jti:
            self.revoked.revoke(jti=jti, user_id=user_id)
        user = self.user_repo.get_by_id(user_id)
        if user is not None:
            self.user_repo.rotate_refresh_token(user, new_jti=None, grace_seconds=0)
        self.db.commit()
        return LogoutResponse()

    # ------------------------------------------------------------------ introspect

    def introspect(self, token: str) -> IntrospectResponse:
        """RFC-7662-shaped introspection. Used by /user/users/introspect."""
        is_valid, is_expired, payload = verify_access_token(token)
        if payload is None:
            return IntrospectResponse(active=False, expired=is_expired)
        # Even if the JWT signature is valid, treat as inactive if jti is revoked
        jti = payload.get("jti")
        if jti and self.revoked.is_revoked(jti):
            return IntrospectResponse(active=False, expired=is_expired)
        return IntrospectResponse(
            active=is_valid,
            expired=is_expired,
            user_id=payload.get("user_id"),
            sub=payload.get("sub"),
            email=payload.get("email"),
            jti=payload.get("jti"),
            iat=payload.get("iat"),
            exp=payload.get("exp"),
        )

    # ------------------------------------------------------------------ /me

    def get_me(self, user_id: str):
        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"User {user_id!r} not found")
        return user
