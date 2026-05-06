"""Self-service password reset (doc 33 change 3 — forgot-password).

Two-stage flow:

1. ``request_password_reset`` — accepts ``{login_or_email, channel}``
   and returns a generic 200 regardless of whether the user exists
   (Q3b.4 anti-enumeration). When the user does exist:
     - ``email`` channel → generates a 32-byte URL-safe token, stores
       its hash, sends a clickable reset link.
     - ``sms`` channel → generates a 6-digit OTP (same generator as
       2FA), stores its hash, sends an SMS.

2. ``perform_password_reset`` — accepts ``{token_or_code, new_password}``,
   looks up the row by hash, verifies it's not expired / consumed,
   updates the user's password, and consumes the row.

Storage: ``password_reset_tokens`` table. TTL via
``PASSWORD_RESET_TTL_SECONDS`` env var (default 3600).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .....core.config import settings
from .....core.security import hash_password
from .....infrastructure.db.models.password_reset_token import (
    PasswordResetTokenModel,
)
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.notifications import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    TEMPLATE_PASSWORD_RESET_LINK,
    TEMPLATE_PASSWORD_RESET_OTP,
    get_notification_client,
)
from .....shared.otp import (
    generate_numeric_code,
    generate_url_token,
    hash_secret,
    verify_secret,
)
from .....shared.service_result import ServiceResult


def _utcnow() -> datetime:
    """Tz-naive UTC, matching how UtcDateTime stores values."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Generic anti-enumeration response shape — used whether the user
# exists or not.
_ANTI_ENUM_RESPONSE = {
    "_type": "PasswordResetRequestAck",
    "message": (
        "If an account matches the provided login/email, a password "
        "reset link or code was sent. Check your inbox or SMS."
    ),
}


def request_password_reset(
    db: Session,
    *,
    login_or_email: str,
    channel: str,
) -> ServiceResult[dict]:
    """Stage 1: send a reset link (email) or OTP (sms).

    Always returns 200 with the generic message regardless of whether
    the user exists, per Q3b.4. Anti-enumeration: an attacker cannot
    determine if a login/email is registered by polling this endpoint.
    """
    if channel not in (CHANNEL_EMAIL, CHANNEL_SMS):
        return ServiceResult.fail(
            error="Channel must be 'email' or 'sms'.",
            error_type="validation_error",
        )

    repo = UserRepository(db)
    user = repo.get_by_login(login_or_email)
    if user is None:
        # Try email. The repo gets-by-login only; do a direct query.
        from .....infrastructure.db.models.user import UserModel
        user = (
            db.query(UserModel)
            .filter(UserModel.email == login_or_email)
            .filter(UserModel.deleted_at.is_(None))
            .first()
        )

    # Inactive users get the same response as missing ones — no
    # enumeration leak via account-state.
    if user is None or user.status != "active":
        return ServiceResult.ok(_ANTI_ENUM_RESPONSE)

    if channel == CHANNEL_SMS and not (user.phone_number or "").strip():
        # Same anti-enumeration: don't tell the caller their phone is
        # missing. Just go through the same response shape — no row
        # written, no notification sent.
        return ServiceResult.ok(_ANTI_ENUM_RESPONSE)

    # Generate the right token form per channel.
    if channel == CHANNEL_EMAIL:
        token = generate_url_token()
        template_kind = TEMPLATE_PASSWORD_RESET_LINK
        payload_secret_label = "reset_token"
    else:  # CHANNEL_SMS
        token = generate_numeric_code(settings.OTP_CODE_LENGTH)
        template_kind = TEMPLATE_PASSWORD_RESET_OTP
        payload_secret_label = "code"

    now = _utcnow()
    ttl = timedelta(seconds=settings.PASSWORD_RESET_TTL_SECONDS)

    row = PasswordResetTokenModel(
        user_id=user.id,
        channel=channel,
        token_hash=hash_secret(token),
        generated_at=now,
        expires_at=now + ttl,
    )
    db.add(row)
    db.commit()

    recipient = user.email if channel == CHANNEL_EMAIL else (user.phone_number or "")
    client = get_notification_client(db)
    client.send(
        user_id=user.id,
        channel=channel,
        recipient=recipient,
        template_kind=template_kind,
        payload={
            payload_secret_label: token,
            "ttl_seconds": settings.PASSWORD_RESET_TTL_SECONDS,
            "purpose": "password_reset",
        },
    )

    return ServiceResult.ok(_ANTI_ENUM_RESPONSE)


def perform_password_reset(
    db: Session,
    *,
    token_or_code: str,
    new_password: str,
) -> ServiceResult[dict]:
    """Stage 2: verify the token + update the password."""
    if not new_password or len(new_password) < 8:
        return ServiceResult.fail(
            error="Password must be at least 8 characters.",
            error_type="validation_error",
        )

    token_hash = hash_secret(token_or_code)
    now = _utcnow()
    row = (
        db.query(PasswordResetTokenModel)
        .filter(PasswordResetTokenModel.token_hash == token_hash)
        .filter(PasswordResetTokenModel.consumed_at.is_(None))
        .first()
    )
    if row is None:
        return ServiceResult.fail(
            error="Invalid or already-used reset token.",
            error_type="invalid_credentials",
        )
    if row.expires_at <= now:
        row.consumed_at = now
        db.commit()
        return ServiceResult.fail(
            error="Reset token has expired. Request a new one.",
            error_type="invalid_credentials",
        )

    repo = UserRepository(db)
    user = repo.get_by_id(row.user_id)
    if user is None or user.status != "active":
        row.consumed_at = now
        db.commit()
        return ServiceResult.fail(
            error="Invalid reset token.",
            error_type="invalid_credentials",
        )

    # Update password + consume.
    repo.update_password(user.id, hash_password(new_password))
    row.consumed_at = now
    db.commit()

    return ServiceResult.ok({
        "_type": "PasswordResetAck",
        "message": "Password updated successfully.",
    })
