"""User database model — owned by pmis-user-service.

Column-for-column identical to the monolith's ``UserModel`` so the shared
Postgres table can be written by user-service and read by backend without
either having a stale mapping.
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String

from ..session import Base


def _utcnow():
    return datetime.now(timezone.utc)


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    login = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    admin = Column(Boolean, default=False, nullable=False)
    status = Column(String(50), default="active", nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Refresh token tracking (single-active-refresh-token per user).
    refresh_token_jti = Column(String(64), nullable=True)
    refresh_token_expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_users_login", "login"),
        Index("idx_users_email", "email"),
        Index("idx_users_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<UserModel(id={self.id}, login='{self.login}', email='{self.email}')>"
