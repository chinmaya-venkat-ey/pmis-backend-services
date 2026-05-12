"""Read-only mirror of the monolith's ``roles`` table.

Only declares the columns the digest cron needs (id + name). The cron
filters role names against a small allow-list of recipient tiers
(``org_admin`` / ``project_admin`` / ``project_member``).
"""
from sqlalchemy import Column, Integer, String

from ..session import Base


class RoleModel(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
