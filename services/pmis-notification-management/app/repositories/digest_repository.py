"""Repository for daily-digest cross-schema queries.

Queries users/projects/milestones/activities for the upcoming-deadline
scan. All reads — never writes (those tables are owned by user-svc and
project-svc).

Ported from the inline queries in
  C:\\Programming\\PMIS\\PMIS-notification-service\\app\\services\\digest_service.py:100-203
extracted into a repository per PLAN.md §1.2 (repositories own data
access, services own logic). Switched from `.query()` to `select()` per
PLAN.md §2.1.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.models._cross_schema import (
    Activity,
    Milestone,
    Project,
    ProjectVendor,
    Role,
    User,
    UserRoleAssignment,
)


# Recipient roles considered for the per-project notification list.
_RECIPIENT_ROLES: Tuple[str, ...] = (
    "org_admin",
    "project_admin",
    "project_member",
)


class DigestRepository:
    """Cross-schema reads for the daily-digest cron."""

    def __init__(self, db: Session):
        self.db = db

    def find_due_milestones(
        self,
        today: date,
        window_days: int,
    ) -> List[Tuple[Project, Milestone]]:
        """Return (project, milestone) for every milestone whose end_date
        falls in (-inf, today + window_days], excluding completed milestones,
        closed/deleted projects, and deleted rows.
        """
        cutoff = datetime.combine(
            today + timedelta(days=window_days + 1), datetime.min.time()
        )
        stmt = (
            select(Milestone, Project)
            .join(Project, Project.id == Milestone.project_id)
            .where(Milestone.deleted_at.is_(None))
            .where(Milestone.status != "completed")
            .where(Milestone.end_date < cutoff)
            .where(Project.deleted_at.is_(None))
            .where(Project.status != "closed")
        )
        rows = self.db.execute(stmt).all()
        return [(p, m) for (m, p) in rows]

    def find_due_activities(
        self,
        today: date,
        window_days: int,
    ) -> List[Tuple[Project, Activity]]:
        """Same as find_due_milestones but for activities. end_date is
        nullable on activities — those rows are skipped."""
        cutoff = datetime.combine(
            today + timedelta(days=window_days + 1), datetime.min.time()
        )
        stmt = (
            select(Activity, Project)
            .join(Project, Project.id == Activity.project_id)
            .where(Activity.deleted_at.is_(None))
            .where(Activity.end_date.is_not(None))
            .where(or_(Activity.status.is_(None), Activity.status != "completed"))
            .where(Activity.end_date < cutoff)
            .where(Project.deleted_at.is_(None))
            .where(Project.status != "closed")
        )
        rows = self.db.execute(stmt).all()
        return [(p, a) for (a, p) in rows]

    def responsible_user_ids(self, project_id: str) -> List[str]:
        """Return distinct active user ids that should receive deadline
        notifications for a given project. Combines:

          - project_admin / project_member rows scoped to the project
          - org_admin rows scoped to any vendor the project is mapped to
        """
        # Resolve the role ids for the three recipient role names.
        role_stmt = select(Role.id, Role.name).where(Role.name.in_(_RECIPIENT_ROLES))
        role_id_to_name: Dict[int, str] = dict(self.db.execute(role_stmt).all())
        if not role_id_to_name:
            return []
        eligible_role_ids = list(role_id_to_name.keys())

        # Vendors mapped to this project — used for org_admin scope match.
        vendor_stmt = select(ProjectVendor.vendor_id).where(
            ProjectVendor.project_id == project_id
        )
        vendor_ids = [row[0] for row in self.db.execute(vendor_stmt).all()]

        # Eligible assignments.
        assn_stmt = (
            select(UserRoleAssignment.user_id, Role.name)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.role_id.in_(eligible_role_ids))
        )
        project_scope = UserRoleAssignment.project_id == project_id
        if vendor_ids:
            org_scope = UserRoleAssignment.organization_id.in_(vendor_ids)
            assn_stmt = assn_stmt.where(or_(project_scope, org_scope))
        else:
            assn_stmt = assn_stmt.where(project_scope)

        user_ids = {row[0] for row in self.db.execute(assn_stmt).all()}
        if not user_ids:
            return []

        # Active + non-deleted + has email.
        active_stmt = (
            select(User.id)
            .where(User.id.in_(user_ids))
            .where(User.status == "active")
            .where(User.deleted_at.is_(None))
            .where(User.email.is_not(None))
        )
        return [row[0] for row in self.db.execute(active_stmt).all()]

    def get_users_by_ids(self, user_ids: List[str]) -> List[User]:
        """Fetch User mirrors for the given ids."""
        if not user_ids:
            return []
        stmt = select(User).where(User.id.in_(user_ids))
        return list(self.db.execute(stmt).scalars().all())
