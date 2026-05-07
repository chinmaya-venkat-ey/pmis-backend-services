"""Scoped role assignment (doc 41).

A row in this table represents "user U holds role R at scope S",
where S is one of:

  * **global**   — both ``organization_id`` and ``project_id`` are NULL.
  * **org**      — ``organization_id`` set, ``project_id`` NULL.
  * **project**  — ``project_id`` set, ``organization_id`` NULL.

The check constraint ``ck_ura_single_scope`` rejects rows that try to
set both scope columns at once (``organization_id`` and ``project_id``
non-NULL together is meaningless: a project's owning vendor is
already implied via ``project_vendors``).

Why a new table instead of widening ``user_roles`` (doc 41 Q2):
``user_roles`` is keyed on ``(user_id, role_id)`` which means a user
can only hold a given role once globally. With scope, we want
"alice holds project_admin on P1 AND project_admin on P2" — two rows
with different ``project_id`` values. A new table with a synthetic
``id`` PK + the existing ``UNIQUE(user_id, role_id, organization_id,
project_id)`` constraint expresses that without breaking the
pre-existing FKs to ``user_roles``.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from ..session import Base
from ..utc_datetime import UtcDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRoleAssignmentModel(Base):
    __tablename__ = "user_role_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)

    user_id = Column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    role_id = Column(
        Integer,
        ForeignKey("roles.id"),
        nullable=False,
        index=True,
    )

    # Exactly-one-scope: ``organization_id`` and ``project_id`` are
    # mutually exclusive (the CHECK constraint enforces that). NULL on
    # both ⇒ global scope (the assignment behaves like the legacy
    # ``user_roles`` row it replaces).
    organization_id = Column(
        String(36),
        ForeignKey("vendors.id"),
        nullable=True,
        index=True,
    )
    project_id = Column(
        String(36),
        ForeignKey("projects.id"),
        nullable=True,
        index=True,
    )

    created_at = Column(UtcDateTime, default=_utcnow, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        # Reject two-scope rows. (org_id IS NULL OR project_id IS NULL).
        CheckConstraint(
            "(organization_id IS NULL) OR (project_id IS NULL)",
            name="ck_ura_single_scope",
        ),
        # No duplicate (user, role, scope) tuples. NULLs participate
        # in uniqueness on Postgres if we use a partial index; for
        # cross-dialect simplicity (test SQLite + prod Postgres), a
        # plain composite UNIQUE plus an explicit "this assignment
        # already exists" service-side check covers the case.
        UniqueConstraint(
            "user_id", "role_id", "organization_id", "project_id",
            name="uq_user_role_assignment_scope",
        ),
        Index("idx_ura_user", "user_id"),
        Index("idx_ura_project", "project_id"),
        Index("idx_ura_org", "organization_id"),
        Index("idx_ura_role", "role_id"),
    )

    def __repr__(self) -> str:
        scope = (
            f"project={self.project_id}" if self.project_id
            else f"org={self.organization_id}" if self.organization_id
            else "global"
        )
        return (
            f"<UserRoleAssignmentModel(id={self.id}, "
            f"user_id={self.user_id}, role_id={self.role_id}, {scope})>"
        )
