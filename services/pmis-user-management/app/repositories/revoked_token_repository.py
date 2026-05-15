"""RevokedTokenRepository — JWT blacklist writes.

Inserting a jti here causes EVERY subsequent authed request across all
services to reject that token (auth middlewares check this table cross-schema
on every request).

Reads of `is_revoked` are also exposed on RbacRepository — that's the
canonical read path used by the AuthMiddleware. This narrower repo exposes
the WRITE path used during logout.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.revoked_token import RevokedToken


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RevokedTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def revoke(
        self,
        *,
        jti: str,
        user_id: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> RevokedToken:
        """Insert a jti into the blacklist. Idempotent — duplicate inserts no-op."""
        existing = self.db.get(RevokedToken, jti)
        if existing is not None:
            return existing
        row = RevokedToken(
            jti=jti,
            user_id=user_id,
            revoked_at=_utcnow(),
            expires_at=expires_at,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        return self.db.get(RevokedToken, jti) is not None
