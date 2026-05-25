"""TeamService — business logic for the Manage-Team page.

Serves six endpoints:
  GET  /projects/{id}/team                — full team snapshot
  PUT  /projects/{id}/team                — bulk save ownership + all activity assignments
  GET  /projects/{id}/ownership           — project owner/approver read
  PUT  /projects/{id}/ownership           — replace project owner/approver
  GET  /activities/{id}/assignments       — single-activity assignments read
  PUT  /activities/{id}/assignments       — replace single-activity assignments
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models._cross_schema import (
    User,
    UserRoleAssignment,
    Role,
)
from app.models.activity import Activity
from app.models.activity_assignment import ActivityAssignment
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.project_ownership import ProjectOwnership
from app.repositories.assignable_users_repository import AssignableUsersRepository
from app.schemas.team import (
    ActivityAssignmentEntry,
    ActivityAssignmentsRead,
    ActivityAssignmentsWrite,
    OrgMemberBucket,
    OrgUserRow,
    OwnershipRead,
    OwnershipWrite,
    ProjectOwnerRow,
    TeamActivityRow,
    TeamPageActivity,
    TeamPageRequest,
    TeamPageResponse,
    TeamReadResponse,
    TeamUserChip,
    TeamWriteRequest,
    TeamWriteResponse,
    UserDirectoryEntry,
)


class TeamService:
    def __init__(self, db: Session):
        self.db = db
        self.assignable_repo = AssignableUsersRepository(db)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _get_project_or_404(self, project_id: str) -> Project:
        proj = self.db.get(Project, project_id)
        if proj is None or proj.deleted_at is not None:
            raise NotFoundError(f"Project {project_id} not found")
        return proj

    def _get_activity_or_404(self, activity_id: str) -> Activity:
        act = self.db.get(Activity, activity_id)
        if act is None or act.deleted_at is not None:
            raise NotFoundError(f"Activity {activity_id} not found")
        return act

    def _hydrate_users(self, user_ids: List[str]) -> List[TeamUserChip]:
        """Fetch user rows for a list of IDs and return TeamUserChip list."""
        if not user_ids:
            return []
        rows = self.db.execute(
            select(User).where(User.id.in_(user_ids)).where(User.deleted_at.is_(None))
        ).scalars().all()
        by_id = {u.id: u for u in rows}
        return [
            TeamUserChip(
                id=uid,
                login=by_id[uid].login if uid in by_id else uid,
                email=by_id[uid].email if uid in by_id else None,
                first_name=by_id[uid].first_name if uid in by_id else None,
                last_name=by_id[uid].last_name if uid in by_id else None,
            )
            for uid in user_ids
            if uid in by_id
        ]

    def _milestone_display_code(self, position: int) -> str:
        return f"M{position}"

    def _activity_display_code(self, ms_position: int, act_position: int) -> str:
        return f"A{ms_position}.{act_position}"

    # ── ownership helpers ────────────────────────────────────────────────────

    def _read_ownership(self, project_id: str) -> OwnershipRead:
        rows = self.db.execute(
            select(ProjectOwnership)
            .where(ProjectOwnership.project_id == project_id)
            .where(ProjectOwnership.deleted_at.is_(None))
        ).scalars().all()

        owner_ids = [r.user_id for r in rows if r.role == "project_owner"]
        approver_ids = [r.user_id for r in rows if r.role == "approver"]
        return OwnershipRead(
            project_owner=self._hydrate_users(owner_ids),
            approver=self._hydrate_users(approver_ids),
        )

    def _write_ownership(
        self, project_id: str, payload: OwnershipWrite, caller_id: Optional[str]
    ) -> None:
        """Replace all ownership rows for the project (idempotent replace)."""
        self.db.execute(
            delete(ProjectOwnership).where(ProjectOwnership.project_id == project_id)
        )
        for uid in set(payload.project_owner):
            self.db.add(ProjectOwnership(
                project_id=project_id, user_id=uid,
                role="project_owner", created_by=caller_id,
            ))
        for uid in set(payload.approver[:1]):  # single approver — take first
            self.db.add(ProjectOwnership(
                project_id=project_id, user_id=uid,
                role="approver", created_by=caller_id,
            ))
        self.db.flush()

    # ── activity assignments helpers ─────────────────────────────────────────

    def _read_activity_assignments(self, activity_id: str) -> ActivityAssignmentsRead:
        rows = self.db.execute(
            select(ActivityAssignment)
            .where(ActivityAssignment.activity_id == activity_id)
            .where(ActivityAssignment.deleted_at.is_(None))
        ).scalars().all()

        owner_ids: List[str] = []
        owner_approver_ids: List[str] = []
        div_user_ids: Dict[str, List[str]] = defaultdict(list)
        div_approver_ids: Dict[str, List[str]] = defaultdict(list)

        for r in rows:
            if r.role == "owner":
                owner_ids.append(r.user_id)
            elif r.role == "owner_approver":
                owner_approver_ids.append(r.user_id)
            elif r.role == "division_user" and r.division_code:
                div_user_ids[r.division_code].append(r.user_id)
            elif r.role == "division_approver" and r.division_code:
                div_approver_ids[r.division_code].append(r.user_id)

        return ActivityAssignmentsRead(
            owner=self._hydrate_users(owner_ids),
            owner_approver=self._hydrate_users(owner_approver_ids),
            division_users={
                div: self._hydrate_users(ids)
                for div, ids in div_user_ids.items()
            },
            division_approvers={
                div: self._hydrate_users(ids)
                for div, ids in div_approver_ids.items()
            },
        )

    def _write_activity_assignments(
        self,
        activity_id: str,
        project_id: str,
        payload: ActivityAssignmentEntry,
        caller_id: Optional[str],
    ) -> None:
        """Replace all assignment rows for one activity."""
        self.db.execute(
            delete(ActivityAssignment)
            .where(ActivityAssignment.activity_id == activity_id)
        )
        def _add(user_id: str, role: str, division_code: Optional[str] = None):
            self.db.add(ActivityAssignment(
                activity_id=activity_id,
                project_id=project_id,
                user_id=user_id,
                role=role,
                division_code=division_code,
                created_by=caller_id,
            ))

        for uid in set(payload.owner):
            _add(uid, "owner")
        for uid in set(payload.owner_approver[:1]):  # single approver
            _add(uid, "owner_approver")
        for div, uids in payload.division_users.items():
            for uid in set(uids):
                _add(uid, "division_user", div)
        for div, uids in payload.division_approvers.items():
            for uid in set(uids[:1]):  # single per division
                _add(uid, "division_approver", div)
        self.db.flush()

    # ── org members (read-only from user_role_assignments) ──────────────────

    def _read_org_members(self, project_id: str) -> List[OrgMemberBucket]:
        rows = self.assignable_repo.list_role_assignments_for_project(project_id)
        buckets: Dict[int, OrgMemberBucket] = {}
        for ura, role, user in rows:
            if role.id not in buckets:
                buckets[role.id] = OrgMemberBucket(
                    role_id=role.id, role_name=role.name, users=[]
                )
            buckets[role.id].users.append(TeamUserChip(
                id=user.id,
                login=user.login,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
            ))
        return list(buckets.values())

    # ── activities with milestone context ────────────────────────────────────

    def _read_team_activities(self, project_id: str) -> List[TeamActivityRow]:
        rows = self.db.execute(
            select(
                Activity,
                Milestone.name.label("ms_name"),
                Milestone.position.label("ms_pos"),
            )
            .join(Milestone, Milestone.id == Activity.milestone_id)
            .where(Activity.project_id == project_id)
            .where(Activity.deleted_at.is_(None))
            .where(Milestone.deleted_at.is_(None))
            .order_by(Milestone.position, Activity.position)
        ).all()

        out: List[TeamActivityRow] = []
        for act, ms_name, ms_pos in rows:
            assignments = self._read_activity_assignments(act.id)
            out.append(TeamActivityRow(
                id=act.id,
                display_code=self._activity_display_code(ms_pos, act.position),
                name=act.name,
                milestone_id=act.milestone_id,
                milestone_name=ms_name,
                milestone_display_code=self._milestone_display_code(ms_pos),
                concerned_divisions=act.concerned_divisions or [],
                assignments=assignments,
            ))
        return out

    # ── public methods ───────────────────────────────────────────────────────

    def get_team(self, project_id: str) -> TeamReadResponse:
        proj = self._get_project_or_404(project_id)

        org_members = self._read_org_members(project_id)
        ownership = self._read_ownership(project_id)
        activities = self._read_team_activities(project_id)

        # Assignable users picker (same as task assignee picker)
        raw_users = self.assignable_repo.list_assignable_users_for_project(project_id)
        assignable = [
            TeamUserChip(
                id=u["id"],
                login=u["login"],
                email=u.get("email"),
                first_name=u.get("first_name"),
                last_name=u.get("last_name"),
            )
            for u in raw_users
        ]

        return TeamReadResponse(
            project_id=proj.id,
            project_code=proj.project_code,
            project_name=proj.name,
            org_members=org_members,
            ownership=ownership,
            activities=activities,
            assignable_users=assignable,
        )

    def save_team(
        self,
        project_id: str,
        payload: TeamWriteRequest,
        caller_id: Optional[str],
    ) -> TeamWriteResponse:
        proj = self._get_project_or_404(project_id)

        updated_ownership = False
        if payload.ownership is not None:
            self._write_ownership(project_id, payload.ownership, caller_id)
            updated_ownership = True

        updated_activities: List[str] = []
        for activity_id, entry in payload.activity_assignments.items():
            act = self.db.get(Activity, activity_id)
            if act is None or act.deleted_at is not None or act.project_id != project_id:
                continue
            self._write_activity_assignments(activity_id, project_id, entry, caller_id)
            updated_activities.append(activity_id)

        self.db.commit()
        return TeamWriteResponse(
            project_id=project_id,
            project_code=proj.project_code,
            updated_ownership=updated_ownership,
            updated_activities=updated_activities,
        )

    def get_ownership(self, project_id: str) -> OwnershipRead:
        self._get_project_or_404(project_id)
        return self._read_ownership(project_id)

    def save_ownership(
        self,
        project_id: str,
        payload: OwnershipWrite,
        caller_id: Optional[str],
    ) -> OwnershipRead:
        self._get_project_or_404(project_id)
        self._write_ownership(project_id, payload, caller_id)
        self.db.commit()
        return self._read_ownership(project_id)

    def get_activity_assignments(self, activity_id: str) -> ActivityAssignmentsRead:
        self._get_activity_or_404(activity_id)
        return self._read_activity_assignments(activity_id)

    def save_activity_assignments(
        self,
        activity_id: str,
        payload: ActivityAssignmentsWrite,
        caller_id: Optional[str],
    ) -> ActivityAssignmentsRead:
        act = self._get_activity_or_404(activity_id)
        entry = ActivityAssignmentEntry(
            owner=payload.owner,
            owner_approver=payload.owner_approver,
            division_users=payload.division_users,
            division_approvers=payload.division_approvers,
        )
        self._write_activity_assignments(activity_id, act.project_id, entry, caller_id)
        self.db.commit()
        return self._read_activity_assignments(activity_id)

    # ── UI-shaped team-page endpoints ────────────────────────────────────────

    @staticmethod
    def _format_display_name(user_dict: Dict[str, Any]) -> str:
        """'First Last (login)' — same compact format as USER_DIRECTORY in HTML."""
        parts = " ".join(
            x for x in [user_dict.get("first_name"), user_dict.get("last_name")] if x
        ).strip()
        login = user_dict.get("login", "")
        return f"{parts} ({login})" if parts else login

    def get_team_page(self, project_id: str) -> TeamPageResponse:
        """Full UI state for GET /projects/{id}/team-page.

        Returns projectId/projectName, userDirectory (assignable users formatted
        for USER_DIRECTORY), and the three state sections (orgUser, projectOwner,
        activities) with user IDs — not full user objects — matching the JS state
        shape exactly so the frontend needs zero transformation.
        """
        proj = self._get_project_or_404(project_id)

        # userDirectory — assignable users formatted for the user picker
        raw_users = self.assignable_repo.list_assignable_users_for_project(project_id)
        user_directory = [
            UserDirectoryEntry(id=u["id"], name=self._format_display_name(u))
            for u in raw_users
        ]

        # orgUser — read from user_role_assignments (read-only on this endpoint)
        org_members = self._read_org_members(project_id)
        org_user = [
            OrgUserRow(role_label=bucket.role_name, users=[c.id for c in bucket.users])
            for bucket in org_members
        ]

        # projectOwner — Approver row always first (single=True), then Project Owner
        ownership = self._read_ownership(project_id)
        project_owner = [
            ProjectOwnerRow(
                role_label="Approver",
                users=[c.id for c in ownership.approver],
                single=True,
            ),
            ProjectOwnerRow(
                role_label="Project Owner",
                users=[c.id for c in ownership.project_owner],
            ),
        ]

        # activities — flat list ordered milestone.position → activity.position
        team_activities = self._read_team_activities(project_id)
        activities = [
            TeamPageActivity(
                id=row.id,
                name=row.name,
                milestone=row.milestone_name,
                concerned_divisions=row.concerned_divisions,
                owner=[c.id for c in row.assignments.owner],
                owner_approver=[c.id for c in row.assignments.owner_approver],
                division_users={
                    div: [c.id for c in chips]
                    for div, chips in row.assignments.division_users.items()
                },
                division_approvers={
                    div: [c.id for c in chips]
                    for div, chips in row.assignments.division_approvers.items()
                },
            )
            for row in team_activities
        ]

        return TeamPageResponse(
            project_id=proj.id,
            project_code=proj.project_code,
            project_name=proj.name,
            user_directory=user_directory,
            org_user=org_user,
            project_owner=project_owner,
            activities=activities,
        )

    def save_team_page(
        self,
        project_id: str,
        payload: TeamPageRequest,
        caller_id: Optional[str],
    ) -> TeamPageResponse:
        """Bulk save for PUT /projects/{id}/team-page (the Submit button).

        Persists projectOwner and all activities. orgUser is accepted in the
        body for schema symmetry but is NOT written here — org-level role
        assignments are owned by the user-management service.
        """
        self._get_project_or_404(project_id)

        # Save project ownership: match rows by roleLabel
        owner_ids: List[str] = []
        approver_ids: List[str] = []
        for row in payload.project_owner:
            label = row.role_label.lower()
            if row.single or label == "approver":
                approver_ids = row.users[:1]
            else:
                owner_ids = row.users

        self._write_ownership(
            project_id,
            OwnershipWrite(project_owner=owner_ids, approver=approver_ids),
            caller_id,
        )

        # Save every activity's assignments
        for act_payload in payload.activities:
            act = self.db.get(Activity, act_payload.id)
            if act is None or act.deleted_at is not None or act.project_id != project_id:
                continue
            self._write_activity_assignments(
                act_payload.id,
                project_id,
                ActivityAssignmentEntry(
                    owner=act_payload.owner,
                    owner_approver=act_payload.owner_approver,
                    division_users=act_payload.division_users,
                    division_approvers=act_payload.division_approvers,
                ),
                caller_id,
            )

        self.db.commit()
        return self.get_team_page(project_id)
