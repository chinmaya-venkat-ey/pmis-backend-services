"""Password reset tokens (doc 33 change 3 — forgot-password flow).

Two channel-dependent token forms:

- ``email`` channel: a 32-byte URL-safe random token sent in a
  clickable reset link. Hashed (HMAC-SHA256 with server pepper) at
  rest so DB readers can't replay it.
- ``sms`` channel: a 6-digit OTP. Hashed identically. URLs are awkward
  in SMS (often broken / phishing-flagged) so the SMS channel uses
  numeric codes the user types in.

Single endpoint accepts either form (the user sends the token they
got, the server hashes + matches).

Always-200 anti-enumeration response: ``POST /users/forgot-password``
ALWAYS returns 200 whether the user exists or not. A row is only
inserted when the user genuinely exists; a non-existent login goes
through the same response timing without writing anything.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Index, Integer, String

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow():
    return datetime.now(timezone.utc)


class PasswordResetTokenModel(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    user_id = Column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    # ``email`` (URL-token) or ``sms`` (OTP).
    channel = Column(String(16), nullable=False)

    # HMAC-SHA256 of the token (URL form) or the numeric OTP.
    token_hash = Column(String(128), nullable=False, unique=True, index=True)

    generated_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    expires_at = Column(UtcDateTime, nullable=False, index=True)
    consumed_at = Column(UtcDateTime, nullable=True, index=True)

    __table_args__ = (
        Index("idx_password_reset_tokens_user_id_active", "user_id", "consumed_at"),
    )
