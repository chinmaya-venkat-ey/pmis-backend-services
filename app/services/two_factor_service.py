"""TwoFactorService — OTP send + verify (Q13: storage in user-svc, dispatch via notification-svc).

Workflow:
  1. AuthService.authenticate raises TwoFactorRequiredError + ephemeral_token
     after a valid password but before issuing tokens. The pending OtpCode
     row exists at this point with `code_hash=None`.
  2. FE calls POST /user/users/login/send-otp with the ephemeral_token →
     `send_otp` generates a code, stores its hash, dispatches via notification-svc.
  3. FE calls POST /user/users/login/verify-otp with the ephemeral_token + code →
     `verify_otp` validates, marks consumed, issues final tokens (delegated to
     AuthService._issue_login).

UNIVERSAL_OTP backdoor (settings.universal_otp_enabled): bypasses code check
in non-prod. AuthMiddleware lifespan refuses to start when this is True in
production (Q14).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app.config import settings
from app.core.errors import (
    DomainError,
    OtpAttemptsExceededError,
    OtpExpiredError,
    OtpInvalidError,
    OtpResendCooldownError,
    UserNotFoundError,
)
from app.repositories.otp_code_repository import OtpCodeRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginResponse
from app.schemas.otp import OtpSendResponse
from app.services.auth_service import AuthService
from app.services.notification_client import NotificationClient
from app.utilities.otp import (
    generate_otp_code,
    hash_ephemeral_token,
    hash_otp_code,
    verify_otp_code,
)



def _mask_email(email: str) -> str:
    if "@" not in email:
        return email
    local, _, domain = email.partition("@")
    masked_local = local[:1] + "*" * max(0, len(local) - 1) if local else "*"
    return f"{masked_local}@{domain}"


def _mask_phone(phone: str) -> str:
    if len(phone) <= 4:
        return phone
    return phone[:3] + "*" * (len(phone) - 5) + phone[-2:]


class TwoFactorService:
    def __init__(self, db: Session):
        self.db = db
        self.otp_repo = OtpCodeRepository(db)
        self.user_repo = UserRepository(db)
        self.notify = NotificationClient(db)

    # ------------------------------------------------------------------ send

    def send_otp(self, ephemeral_token: str, channel: str) -> OtpSendResponse:
        eph_hash = hash_ephemeral_token(ephemeral_token)
        # Bug #240: resolve by the SESSION window (generated_at within
        # otp_session_ttl), not the current code's expiry — so a user can
        # request a fresh code even after the previous one expired, without
        # re-entering credentials. The session is still capped, so a stale
        # ephemeral token can't keep an attempt alive forever.
        row = self.otp_repo.get_resumable_by_ephemeral_token(
            eph_hash, session_ttl_seconds=settings.otp_session_ttl_seconds,
        )
        if row is None:
            raise OtpInvalidError("OTP session not found or expired")

        user = self.user_repo.get_by_id(row.user_id)
        if user is None or user.deleted_at is not None:
            raise UserNotFoundError("User no longer available for this OTP session")

        now = datetime.now(timezone.utc)
        # Gap G4: enforce the resend cooldown. The first dispatch (row has no
        # code yet) is exempt; resends within the window are rejected with 429
        # + remaining_seconds so the FE can render "wait N seconds".
        if row.code_hash is not None and row.last_sent_at is not None:
            elapsed = (now - row.last_sent_at).total_seconds()
            if elapsed < settings.otp_resend_cooldown_seconds:
                remaining = max(1, int(settings.otp_resend_cooldown_seconds - elapsed))
                raise OtpResendCooldownError(
                    f"Please wait {remaining}s before requesting another code",
                    details={"remaining_seconds": remaining},
                )

        recipient = self._recipient_for_channel(user, channel)
        code = generate_otp_code(settings.otp_code_length)
        self.otp_repo.set_code(row, code_hash=hash_otp_code(code))
        # Update channel if FE chose differently from the seed + stamp the
        # send-time so the next resend's cooldown is measurable.
        row.channel = channel
        row.last_sent_at = now
        self.db.commit()

        # Dispatch to notification-svc with payload {code, ttl_seconds}.
        self.notify.dispatch(
            user_id=user.id,
            channel=channel,
            recipient=recipient,
            template_kind="otp_login",
            payload={"code": code, "ttl_seconds": settings.otp_ttl_seconds},
        )

        masked = _mask_email(recipient) if channel == "email" else _mask_phone(recipient)
        return OtpSendResponse(channel=channel, masked_destination=masked)

    def _recipient_for_channel(self, user, channel: str) -> str:
        if channel == "email":
            return user.email
        if channel == "sms":
            if not user.phone_number:
                raise OtpInvalidError("User has no phone number on file")
            return user.phone_number
        raise OtpInvalidError(f"Unsupported channel: {channel}")

    # ------------------------------------------------------------------ verify

    def verify_otp(self, ephemeral_token: str, code: str) -> LoginResponse:
        eph_hash = hash_ephemeral_token(ephemeral_token)
        # Bug #240: resolve by session window so an expired code yields a clear
        # "expired — request a new code" rather than "session not found". The
        # code's own expiry is enforced explicitly just below.
        row = self.otp_repo.get_resumable_by_ephemeral_token(
            eph_hash, session_ttl_seconds=settings.otp_session_ttl_seconds,
        )
        if row is None:
            raise OtpInvalidError("OTP session not found")
        if row.consumed_at is not None:
            raise OtpInvalidError("OTP already used")
        from datetime import datetime, timezone
        if row.expires_at and row.expires_at < datetime.now(timezone.utc):
            raise OtpExpiredError("OTP has expired — please request a new code")
        if row.attempt_count >= settings.otp_max_attempts:
            raise OtpAttemptsExceededError("OTP max attempts exceeded")

        # UNIVERSAL_OTP backdoor — never True in production (Q14 startup guard).
        is_universal_match = (
            settings.universal_otp_enabled
            and code == settings.universal_otp_code
        )

        if not (is_universal_match or (row.code_hash and verify_otp_code(code, row.code_hash))):
            self.otp_repo.increment_attempts(row)
            self.db.commit()
            raise OtpInvalidError("OTP code incorrect")

        # Success — consume the row and issue tokens.
        self.otp_repo.consume(row)
        self.db.commit()

        user = self.user_repo.get_by_id(row.user_id)
        if user is None:
            raise UserNotFoundError("User no longer available")
        return AuthService(self.db)._issue_login(user)
