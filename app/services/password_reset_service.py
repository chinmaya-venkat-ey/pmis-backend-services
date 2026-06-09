"""PasswordResetService — forgot + reset flows.

forgot: always returns 200 (anti-enumeration). Quietly no-ops if the user
doesn't exist.

reset: validates the single-use HMAC token, updates the user's password,
marks the token consumed, and revokes all in-flight refresh tokens for that
user (so any session that knew the old password is invalidated).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import PasswordResetTokenInvalidError, UserNotFoundError
from app.core.security import hash_password
from app.repositories.password_reset_token_repository import PasswordResetTokenRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.password import ForgotPasswordResponse, ResetPasswordResponse
from app.services.notification_client import NotificationClient
from app.utilities.logger import get_logger
from app.utilities.password_reset import (
    generate_reset_token,
    hash_reset_token,
    verify_reset_token,
)


logger = get_logger(__name__)


class PasswordResetService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.token_repo = PasswordResetTokenRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)
        self.notify = NotificationClient(db)

    def request_reset(self, login: str, channel: str) -> ForgotPasswordResponse:
        """Always returns success (anti-enumeration). Sends a real email/SMS
        if the user exists; quietly no-ops otherwise."""
        user = self.user_repo.get_by_login(login) or self.user_repo.get_by_email(login)
        if user is None or user.deleted_at is not None:
            logger.info("password reset: no match for login=%r — silent success", login)
            return ForgotPasswordResponse()

        token = generate_reset_token()
        self.token_repo.create(
            user_id=user.id,
            channel=channel,
            token_hash=hash_reset_token(token),
        )
        self.db.commit()

        # Dispatch — different templates for email vs sms.
        if channel == "email":
            template_kind = "password_reset_link"
            recipient = user.email
            payload = {
                "reset_token": token,
                "ttl_seconds": settings.password_reset_ttl_seconds,
            }
        else:
            template_kind = "password_reset_otp"
            recipient = user.phone_number or ""
            payload = {
                "code": token,  # SMS receives the raw token as a code-like string
                "ttl_seconds": settings.password_reset_ttl_seconds,
            }

        if recipient:
            self.notify.dispatch(
                user_id=user.id,
                channel=channel,
                recipient=recipient,
                template_kind=template_kind,
                payload=payload,
            )
        return ForgotPasswordResponse()

    def perform_reset(self, token: str, new_password: str) -> ResetPasswordResponse:
        row = self.token_repo.get_active_by_hash(hash_reset_token(token))
        if row is None:
            raise PasswordResetTokenInvalidError("Reset token invalid or expired")

        user = self.user_repo.get_by_id(row.user_id)
        if user is None or user.deleted_at is not None:
            raise UserNotFoundError("Account not available")

        # Set new password + invalidate any current refresh state (logout-everywhere).
        self.user_repo.set_password(user, hash_password(new_password))
        self.refresh_repo.revoke_all_for_user(user.id)
        self.token_repo.mark_consumed(row)
        self.db.commit()
        return ResetPasswordResponse()
