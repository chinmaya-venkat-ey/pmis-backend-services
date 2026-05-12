"""Read-only mirror of the monolith / user-service ``users`` table.

Only the columns the daily-digest cron needs: who to email, what name
to greet them by, and a soft-delete flag so deleted users are skipped.
"""
from sqlalchemy import Column, DateTime, String

from ..session import Base


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, index=True)
    login = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)
