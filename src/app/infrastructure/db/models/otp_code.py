"""OTP codes table (doc 33 change 3 — 2FA).

The 2FA login flow is two-stage:

1. ``POST /users/login`` with login + password → returns
   ``{requires_otp, ephemeral_token, channels_available}`` when 2FA is
   on for the user. No JWT minted.
2. ``POST /users/login/send-otp`` → generates an OTP, stamps an
   ``otp_codes`` row, dispatches via the notification client.
3. ``POST /users/login/verify-otp`` → checks the code, mints the real
   access + refresh JWT.

Storage rules:
- ``code_hash`` stores HMAC-SHA256(server_pepper, code). Reading the
  DB does NOT reveal active codes.
- ``ephemeral_token_hash`` is the hash of the opaque token returned
  to the client at stage 1. Used to look up which OTP row a verify
  call refers to.
- ``consumed_at`` set on successful verify → row becomes single-use.
- ``attempt_count`` increments on wrong-code submits; once it hits
  ``OTP_MAX_ATTEMPTS`` the row is invalidated (consumed_at = now).
- Rows are not deleted, just consumed/expired — the audit trail of
  who attempted what stays.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Index, Integer, String

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class OtpCodeModel(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    user_id = Column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    # ``email`` or ``sms``.
    channel = Column(String(16), nullable=False)

    # HMAC-SHA256 of the actual code (with server pepper). 64 hex chars.
    code_hash = Column(String(128), nullable=False)

    # HMAC-SHA256 of the ephemeral session token returned at /login
    # stage 1. Indexed to look up rows by token. NOT unique — a
    # sentinel row written at /login is followed by additional rows
    # on each send/resend (each with its own code_hash and
    # last_sent_at). The lookup query picks the latest active row.
    ephemeral_token_hash = Column(String(128), nullable=False, index=True)

    generated_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    expires_at = Column(UtcDateTime, nullable=False, index=True)
    consumed_at = Column(UtcDateTime, nullable=True, index=True)

    attempt_count = Column(Integer, nullable=False, default=0)

    # Optional last-resend bookkeeping for the cooldown check.
    last_sent_at = Column(UtcDateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("idx_otp_codes_user_id_active", "user_id", "consumed_at"),
    )
