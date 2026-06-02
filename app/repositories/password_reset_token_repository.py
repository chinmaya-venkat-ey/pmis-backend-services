"""PasswordResetTokenRepository — generate + consume single-use reset tokens."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.password_reset_token import PasswordResetToken


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PasswordResetTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: str,
        channel: str,
        token_hash: str,
        ttl_seconds: Optional[int] = None,
    ) -> PasswordResetToken:
        now = _utcnow()
        ttl = ttl_seconds if ttl_seconds is not None else settings.password_reset_ttl_seconds
        row = PasswordResetToken(
            user_id=user_id,
            channel=channel,
            token_hash=token_hash,
            generated_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def get_active_by_hash(self, token_hash: str) -> Optional[PasswordResetToken]:
        """Find a non-expired, non-consumed token by hash."""
        now = _utcnow()
        stmt = (
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .where(PasswordResetToken.consumed_at.is_(None))
            .where(PasswordResetToken.expires_at >= now)
        )
        return self.db.execute(stmt).scalars().first()

    def mark_consumed(self, row: PasswordResetToken) -> PasswordResetToken:
        row.consumed_at = _utcnow()
        self.db.flush()
        return row
