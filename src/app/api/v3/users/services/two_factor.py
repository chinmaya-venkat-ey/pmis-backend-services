"""Two-factor authentication service (doc 33 change 3).

Three-stage 2FA login flow:

1. ``authenticate_user`` (existing, in ``authenticate.py``) — verifies
   password. With 2FA on, no JWT is minted; instead an ephemeral
   token + ``requires_otp=True`` is returned. The route layer wraps
   this into ``start_2fa_session`` which calls
   ``begin_otp_challenge`` here.

2. ``send_or_resend_otp`` — generates a fresh OTP, hashes it, stamps
   the row, and dispatches via the notification client. Resends are
   rate-limited by ``OTP_RESEND_COOLDOWN_SECONDS``. Each resend
   invalidates the previous code by stamping ``consumed_at`` on the
   prior row (single-use semantics: only the latest live code counts).

3. ``verify_otp`` — looks up the active OTP row by ephemeral-token
   hash, verifies the code (constant-time), increments ``attempt_count``
   on a miss (and consumes the row at ``OTP_MAX_ATTEMPTS``), and on
   success consumes the row + mints the real JWT pair.

Per Q3a.4: ``REQUIRE_2FA=True`` globally is the default — every user
goes through this flow unless an admin set ``two_factor_enabled=False``
on their account. ``REQUIRE_2FA=False`` short-circuits the entire
flow regardless of the per-user flag.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .....core.config import settings
from .....core.security import create_access_token, create_refresh_token
from .....infrastructure.db.models.otp_code import OtpCodeModel
from .....infrastructure.db.models.user import UserModel
from .....infrastructure.db.repositories.user_repository import UserRepository
from .....shared.notifications import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    TEMPLATE_OTP_LOGIN,
    get_notification_client,
)
from .....shared.otp import (
    generate_ephemeral_token,
    generate_numeric_code,
    hash_secret,
    verify_secret,
)
from .....shared.service_result import ServiceResult


def _utcnow() -> datetime:
    """Tz-naive UTC, matching how UtcDateTime stores values."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_2fa_required_for(user: UserModel) -> bool:
    """Per Q3a.4: 2FA is on by default + per-user override.

    - Global ``REQUIRE_2FA=False`` → 2FA is off for everyone (escape hatch).
    - Otherwise the per-user flag wins.
    """
    if not settings.REQUIRE_2FA:
        return False
    return bool(getattr(user, "two_factor_enabled", True))


def _channels_available(user: UserModel) -> list[str]:
    """Email is always available (signup requires it). SMS only when a
    phone number is on file."""
    out = [CHANNEL_EMAIL]
    if (user.phone_number or "").strip():
        out.append(CHANNEL_SMS)
    return out


def begin_otp_challenge(
    db: Session, user: UserModel,
) -> ServiceResult[dict]:
    """Mint a fresh ephemeral session token + return the channel list.

    Writes a sentinel ``otp_codes`` row keyed on the token hash so the
    later /login/send-otp call can resolve token → user. The sentinel
    is created with ``consumed_at=now`` and an empty ``code_hash`` —
    it cannot be used to verify; it only persists the mapping. The
    real OTP row is inserted by send_or_resend_otp on the first send.

    No OTP is generated yet — that happens when the client picks a
    channel and calls /login/send-otp. This separation lets the FE
    show a "Send to email or SMS?" picker before any notification
    fires.
    """
    ephemeral_token = generate_ephemeral_token()
    token_hash = hash_secret(ephemeral_token)
    now = _utcnow()
    ttl = timedelta(seconds=settings.OTP_TTL_SECONDS)
    sentinel = OtpCodeModel(
        user_id=user.id,
        channel="email",  # placeholder; real channel set on first send
        code_hash="",     # empty hash → constant-time compare always fails
        ephemeral_token_hash=token_hash,
        generated_at=now,
        expires_at=now + ttl,
        consumed_at=now,  # sentinel: can never be verified against
        last_sent_at=now - timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS + 1),  # cooldown elapsed
        attempt_count=0,
    )
    db.add(sentinel)
    db.commit()
    return ServiceResult.ok({
        "requires_otp": True,
        "ephemeral_token": ephemeral_token,
        "ephemeral_token_hash": token_hash,
        "channels_available": _channels_available(user),
        "user_id": user.id,
    })


def send_or_resend_otp(
    db: Session,
    *,
    user_id: str,
    ephemeral_token: str,
    channel: str,
) -> ServiceResult[dict]:
    """Generate + dispatch an OTP for the given ephemeral session.

    First call (no existing row for the token hash): inserts a fresh
    row.

    Subsequent calls (resend): if the cooldown hasn't elapsed since
    the previous send, returns 429-style ``cooldown`` error. Otherwise
    invalidates the previous row (consumed_at = now) and inserts a
    fresh one. The cooldown deters automated abuse + notification spam.
    """
    repo = UserRepository(db)
    user = repo.get_by_id(user_id)
    if user is None or user.status != "active":
        return ServiceResult.fail(
            error="Invalid session.", error_type="invalid_credentials",
        )

    if channel not in (CHANNEL_EMAIL, CHANNEL_SMS):
        return ServiceResult.fail(
            error="Channel must be 'email' or 'sms'.",
            error_type="validation_error",
        )

    if channel == CHANNEL_SMS and not (user.phone_number or "").strip():
        return ServiceResult.fail(
            error="No phone number on file for SMS delivery.",
            error_type="validation_error",
        )

    token_hash = hash_secret(ephemeral_token)
    now = _utcnow()
    cooldown = timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    ttl = timedelta(seconds=settings.OTP_TTL_SECONDS)

    # Find the active (unconsumed, not-expired) row for this token.
    existing = (
        db.query(OtpCodeModel)
        .filter(OtpCodeModel.ephemeral_token_hash == token_hash)
        .filter(OtpCodeModel.consumed_at.is_(None))
        .filter(OtpCodeModel.expires_at > now)
        .first()
    )

    if existing is not None:
        if (now - existing.last_sent_at) < cooldown:
            remaining = int((cooldown - (now - existing.last_sent_at)).total_seconds())
            return ServiceResult.fail(
                error=(
                    f"Please wait {remaining}s before requesting another OTP."
                ),
                error_type="cooldown",
                details={"errorIdentifier": "cooldown", "remaining_seconds": remaining},
            )
        # Cooldown elapsed — invalidate the old row and fall through to
        # generate a new code. Single-use semantics: the previous code
        # cannot be used after a resend.
        existing.consumed_at = now
        db.flush()

    code = generate_numeric_code(settings.OTP_CODE_LENGTH)
    row = OtpCodeModel(
        user_id=user.id,
        channel=channel,
        code_hash=hash_secret(code),
        ephemeral_token_hash=token_hash,
        generated_at=now,
        expires_at=now + ttl,
        last_sent_at=now,
        attempt_count=0,
    )
    db.add(row)
    db.commit()

    recipient = user.email if channel == CHANNEL_EMAIL else (user.phone_number or "")
    client = get_notification_client(db)
    client.send(
        user_id=user.id,
        channel=channel,
        recipient=recipient,
        template_kind=TEMPLATE_OTP_LOGIN,
        payload={
            "code": code,
            "ttl_seconds": settings.OTP_TTL_SECONDS,
            "purpose": "login_2fa",
        },
    )

    return ServiceResult.ok({
        "channel": channel,
        "expires_in_seconds": settings.OTP_TTL_SECONDS,
        "resend_after_seconds": settings.OTP_RESEND_COOLDOWN_SECONDS,
    })


def verify_otp(
    db: Session,
    *,
    ephemeral_token: str,
    code: str,
) -> ServiceResult[dict]:
    """Verify a submitted OTP. On success, mint and return real JWTs.

    Doc 35 — universal OTP escape hatch: when
    ``settings.UNIVERSAL_OTP_ENABLED`` is true and the submitted code
    equals ``settings.UNIVERSAL_OTP_CODE``, the per-row hash check is
    bypassed and the row is consumed as a normal success. The active
    OTP session row (created by /login and /login/send-otp) is still
    required, so the universal OTP can only be used after the user has
    completed the password step. Used as a break-glass for envs where
    notification dispatch is broken — NOT for production.
    """
    token_hash = hash_secret(ephemeral_token)
    now = _utcnow()

    row = (
        db.query(OtpCodeModel)
        .filter(OtpCodeModel.ephemeral_token_hash == token_hash)
        .filter(OtpCodeModel.consumed_at.is_(None))
        .first()
    )
    if row is None:
        return ServiceResult.fail(
            error="OTP session not found or already used.",
            error_type="invalid_credentials",
        )

    if row.expires_at <= now:
        # Mark consumed so a stale token can't be retried.
        row.consumed_at = now
        db.commit()
        return ServiceResult.fail(
            error="OTP has expired. Request a new one.",
            error_type="invalid_credentials",
        )

    # Universal OTP check runs FIRST so a wrong real code that happens
    # to equal the universal value isn't burned against the attempt
    # counter. The user must still have completed /login/send-otp
    # (creating an unconsumed row) — that's already enforced by the
    # row lookup above. The break-glass is "the dispatch failed but
    # the row exists", not "skip the whole flow".
    universal_ok = bool(
        settings.UNIVERSAL_OTP_ENABLED
        and settings.UNIVERSAL_OTP_CODE
        and code == settings.UNIVERSAL_OTP_CODE
    )

    if not universal_ok and not verify_secret(code, row.code_hash):
        row.attempt_count = (row.attempt_count or 0) + 1
        if row.attempt_count >= settings.OTP_MAX_ATTEMPTS:
            row.consumed_at = now
            db.commit()
            return ServiceResult.fail(
                error="Too many wrong attempts. Request a new OTP.",
                error_type="invalid_credentials",
            )
        db.commit()
        remaining = settings.OTP_MAX_ATTEMPTS - row.attempt_count
        return ServiceResult.fail(
            error=f"Wrong code. {remaining} attempt(s) remaining.",
            error_type="invalid_credentials",
            details={"remaining_attempts": remaining},
        )

    # Code matches (real or universal). Consume the row and mint real tokens.
    row.consumed_at = now

    repo = UserRepository(db)
    user = repo.get_by_id(row.user_id)
    if user is None or user.status != "active":
        db.commit()
        return ServiceResult.fail(
            error="User no longer active.", error_type="authentication_error",
        )

    token_data = {
        "sub": user.login,
        "user_id": user.id,
        "email": user.email,
    }
    access_token = create_access_token(token_data)
    refresh_token, refresh_jti, refresh_expires = create_refresh_token(token_data)
    repo.rotate_refresh_token(
        user.id, refresh_jti, refresh_expires,
        grace_seconds=settings.REFRESH_TOKEN_GRACE_SECONDS,
    )

    db.commit()
    return ServiceResult.ok({
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "user": user,
    })
