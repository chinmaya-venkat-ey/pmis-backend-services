"""
Revoked-token registry — backs the access-token blacklist for hard logout.

When a user logs out (or any other revocation flow runs), the access token's
``jti`` claim is inserted here with the token's natural ``expires_at``. The
auth middleware checks this table on every authenticated request and rejects
any token whose ``jti`` is present AND whose ``expires_at`` is still in the
future.

Rows past ``expires_at`` are harmless (the token has expired naturally and
will be rejected by the JWT verifier on its own); a periodic cleanup can
delete them but isn't required for correctness.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class RevokedTokenModel(Base):
    __tablename__ = "revoked_tokens"

    # The JWT's ``jti`` claim is a 32-char hex (uuid4().hex). We use it as
    # the natural primary key so duplicate revocations are a no-op.
    jti = Column(String(64), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    revoked_at = Column(DateTime, default=_utcnow, nullable=False)
    # The token's natural exp claim, in UTC. Once now > expires_at, this row
    # no longer has any effect on auth (the JWT verifier rejects expired
    # tokens unconditionally), so it can safely be cleaned up by a cron.
    expires_at = Column(DateTime, nullable=False, index=True)

    __table_args__ = (
        Index("idx_revoked_tokens_user", "user_id"),
        Index("idx_revoked_tokens_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<RevokedTokenModel(jti='{self.jti[:8]}..', user_id={self.user_id})>"
