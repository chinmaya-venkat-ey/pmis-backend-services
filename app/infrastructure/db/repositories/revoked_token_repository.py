"""Repository for the access-token revocation blacklist.

Both user-service (writer on logout) and backend (reader on every
authenticated request) use this table. User-service owns writes; backend
only performs SELECTs.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..models.revoked_token import RevokedTokenModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RevokedTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def is_revoked(self, jti: str) -> bool:
        """True iff ``jti`` is in the blacklist AND expiry is still in the
        future. Past-expiry rows are ignored — the JWT verifier rejects
        expired tokens anyway.
        """
        if not jti:
            return False
        row = (
            self.db.query(RevokedTokenModel.jti)
            .filter(
                and_(
                    RevokedTokenModel.jti == jti,
                    RevokedTokenModel.expires_at > _utcnow(),
                )
            )
            .first()
        )
        return row is not None

    def revoke(
        self, *, jti: str, expires_at: datetime, user_id: Optional[int] = None,
    ) -> None:
        """Insert a revocation row. Idempotent — re-revoking a jti is a
        silent no-op. Caller is responsible for commit.
        """
        if not jti:
            return
        existing = (
            self.db.query(RevokedTokenModel.jti)
            .filter(RevokedTokenModel.jti == jti)
            .first()
        )
        if existing is not None:
            return
        self.db.add(
            RevokedTokenModel(
                jti=jti,
                user_id=user_id,
                expires_at=expires_at,
            )
        )
        self.db.flush()

    def cleanup_expired(self) -> int:
        """Delete rows whose ``expires_at`` is past. Disk-space optimization;
        not wired to any cron yet. Returns the number of rows deleted.
        """
        deleted = (
            self.db.query(RevokedTokenModel)
            .filter(RevokedTokenModel.expires_at <= _utcnow())
            .delete(synchronize_session=False)
        )
        self.db.flush()
        return deleted
