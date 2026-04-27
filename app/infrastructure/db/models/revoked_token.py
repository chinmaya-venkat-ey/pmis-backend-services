"""Revoked-token registry — access-token blacklist for hard logout.

When a user logs out, the access token's ``jti`` is inserted here with
its natural ``expires_at``. Any service verifying tokens (user-service
itself, or the backend) checks this table and rejects tokens whose
``jti`` is present AND ``expires_at`` is still in the future.

Rows past ``expires_at`` are harmless — the JWT verifier rejects them
on signature/exp grounds anyway. A periodic cleanup job is optional.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RevokedTokenModel(Base):
    __tablename__ = "revoked_tokens"

    # JWT jti is uuid4().hex (32 chars). Used as the natural PK so
    # re-revoking the same token is a silent no-op.
    jti = Column(String(64), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    revoked_at = Column(DateTime, default=_utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)

    __table_args__ = (
        Index("idx_revoked_tokens_user", "user_id"),
        Index("idx_revoked_tokens_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<RevokedTokenModel(jti='{self.jti[:8]}..', user_id={self.user_id})>"
