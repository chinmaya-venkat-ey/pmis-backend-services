"""user_role_assignments — Doc-41 SCOPED role assignments.

Each row binds a (user, role) at exactly ONE of three scope levels:
  - global  (organization_id = NULL, project_id = NULL)
  - org     (organization_id NOT NULL, project_id = NULL)
  - project (organization_id = NULL, project_id NOT NULL)

The CHECK constraint enforces "exactly one of org/project is NULL" — both
NULL → global; both non-NULL is REJECTED.

`organization_id` and `project_id` are LOGICAL cross-schema FKs to
masters.vendors.id and project.projects.id respectively. DB-level FK
constraints are not enforced (cross-service migrations can't guarantee
target tables exist at this migration's runtime). App layer (services)
validates referential integrity.

WARNING: Mirrored in services/pmis-{masters,project,notification}-management.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"
    __table_args__ = (
        # "Exactly one (or none, for global) of org/project must be set":
        #   (org=NULL AND project=NULL)  → global
        #   (org NOT NULL AND project=NULL) → org-scope
        #   (org=NULL AND project NOT NULL) → project-scope
        #   (org NOT NULL AND project NOT NULL) → REJECT
        CheckConstraint(
            "NOT (organization_id IS NOT NULL AND project_id IS NOT NULL)",
            name="ck_ura_single_scope",
        ),
        # Idempotent grant: same (user, role, scope) row can exist only once.
        UniqueConstraint(
            "user_id", "role_id", "organization_id", "project_id",
            name="uq_ura_user_role_scope",
        ),
        Index("ix_ura_user_id", "user_id"),
        Index("ix_ura_role_id", "role_id"),
        Index("ix_ura_organization_id", "organization_id"),
        Index("ix_ura_project_id", "project_id"),
        {"schema": "users"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.users.id"),
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("users.roles.id"),
    )
    # Cross-schema logical FKs (no DB constraint).
    organization_id: Mapped[Optional[str]] = mapped_column(String(36))
    project_id: Mapped[Optional[str]] = mapped_column(String(36))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.users.id"),
    )
