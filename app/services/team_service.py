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

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.models._cross_schema import (
    User,
    UserRoleAssignment,
    Role,
    Vendor,
)
from app.models.activity import Activity
from app.models.activity_assignment import ActivityAssignment
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.project_ownership import ProjectOwnership
from app.repositories.assignable_users_repository import AssignableUsersRepository
from app.repositories.associated_users_repository import AssociatedUsersRepository
from app.services.user_mgmt_client import UserMgmtClient
from app.schemas.team import (
    ActivityAssignmentEntry,
    ActivityAssignmentsRead,
    ActivityAssignmentsWrite,
    AssociatedUserEntry,
    AssociatedUsersFilter,
    AssociatedUsersResponse,
    DivisionRef,
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
    VendorRef,
)


# Bug #161: the FE renders exactly these two "Organization User" rows, in this
# order, and matches them to the API response by position. The backend must
# always emit both, in this order.
_ORG_USER_ROLE_ORDER = ("project_admin", "project_member")


class TeamService:
    def __init__(self, db: Session):
        self.db = db
        self.assignable_repo = AssignableUsersRepository(db)
        self.associated_repo = AssociatedUsersRepository(db)
        self.user_mgmt_client = UserMgmtClient()

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
                full_name=by_id[uid].full_name if uid in by_id else None,
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
                full_name=user.full_name,
            ))
        return list(buckets.values())

    # ── activities with milestone context ────────────────────────────────────

    def _read_team_activities(self, project_id: str) -> List[TeamActivityRow]:
        # Skip activities under the meeting milestone — the team-management
        # page is for project deliverables, not the hidden meeting roster.
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
            .where(Milestone.is_meeting.is_(False))
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
                owner_division=act.owner_division,
                concerned_divisions=act.concerned_divisions or [],
                assignments=assignments,
            ))
        return out

    # ── public methods ───────────────────────────────────────────────────────

    def get_team(self, project_id: str, *, authorization: str = "") -> TeamReadResponse:
        proj = self._get_project_or_404(project_id)

        org_members = self._read_org_members(project_id)
        ownership = self._read_ownership(project_id)
        activities = self._read_team_activities(project_id)

        # Assignable users picker (same as task assignee picker)
        raw_users = self.assignable_repo.list_assignable_users_for_project(
            project_id, authorization=authorization,
        )
        assignable = [
            TeamUserChip(
                id=u["id"],
                login=u["login"],
                email=u.get("email"),
                full_name=u.get("full_name"),
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

    # ── associated users (POST /associated-users) ────────────────────────────

    def get_associated_users(
        self,
        payload: AssociatedUsersFilter,
    ) -> AssociatedUsersResponse:
        """Return users matching one or more of: a project's organizations,
        a project's owner division, or a specific division id.

        See AssociatedUsersFilter docstring for flag semantics. Validation:
          - at least one details flag must be true (else 422)
          - orgDetails / ownerDetails require projectId (else 422)
          - divisionDetails requires divisionId (else 422)
          - projectId must point at a live project (else 404)
          - divisionId must point at a row in masters.divisions (else 422)
        """
        # ---- validate flag/input combinations ---------------------------------
        if not (payload.org_details or payload.owner_details or payload.division_details):
            raise ValidationError(
                "At least one details flag (orgDetails / ownerDetails / divisionDetails) must be true",
                code="no_details_flag",
            )

        if (payload.org_details or payload.owner_details) and not payload.project_id:
            raise ValidationError(
                "orgDetails and ownerDetails require projectId",
                code="project_id_required",
                details={
                    "orgDetails": payload.org_details,
                    "ownerDetails": payload.owner_details,
                },
            )

        if payload.division_details and payload.division_id is None:
            raise ValidationError(
                "divisionDetails requires divisionId",
                code="division_id_required",
            )

        # ---- resolve sources --------------------------------------------------
        project: Optional[Project] = None
        if payload.project_id and (payload.org_details or payload.owner_details):
            project = self._get_project_or_404(payload.project_id)

        vendor_ids_for_orgs: List[str] = []
        if payload.org_details and project is not None:
            vendor_ids_for_orgs = self.associated_repo.get_project_organization_ids(project.id)

        owner_division_code: Optional[str] = None
        if payload.owner_details and project is not None:
            owner_division_code = project.owner  # may be None

        target_division = None
        if payload.division_details:
            target_division = self.associated_repo.get_division_by_id(payload.division_id)
            if target_division is None:
                raise ValidationError(
                    f"Division id {payload.division_id} not found in masters.divisions",
                    code="invalid_division_id",
                    details={"division_id": payload.division_id},
                )

        # ---- build the user-lookup filters -----------------------------------
        division_codes_for_lookup: List[str] = []
        if owner_division_code:
            division_codes_for_lookup.append(owner_division_code)
        if target_division is not None and target_division.code not in division_codes_for_lookup:
            division_codes_for_lookup.append(target_division.code)

        user_rows = self.associated_repo.fetch_users(
            vendor_ids_for_orgs, division_codes_for_lookup,
        )

        # ---- hydrate vendor + division metadata ------------------------------
        vendor_meta = self.associated_repo.get_vendors_by_ids(vendor_ids_for_orgs)
        division_codes_to_hydrate = [c for c in (owner_division_code,) if c]
        owner_division_meta = self.associated_repo.get_divisions_by_codes(
            division_codes_to_hydrate
        )

        vendor_set = set(vendor_ids_for_orgs)

        users_out: List[AssociatedUserEntry] = []
        for u in user_rows:
            matched_orgs: List[VendorRef] = []
            matched_owner_div: List[DivisionRef] = []
            matched_div: List[DivisionRef] = []

            if payload.org_details and u.vendor_id and u.vendor_id in vendor_set:
                v = vendor_meta.get(u.vendor_id)
                matched_orgs.append(VendorRef(
                    id=u.vendor_id,
                    name=v.name if v else None,
                ))

            if (
                payload.owner_details
                and owner_division_code
                and u.division
                and u.division == owner_division_code
            ):
                d = owner_division_meta.get(u.division)
                matched_owner_div.append(DivisionRef(
                    id=d.id if d else None,
                    code=u.division,
                    name=d.label if d else None,
                ))

            if (
                payload.division_details
                and target_division is not None
                and u.division
                and u.division == target_division.code
            ):
                matched_div.append(DivisionRef(
                    id=target_division.id,
                    code=target_division.code,
                    name=target_division.label,
                ))

            if not matched_orgs and not matched_owner_div and not matched_div:
                # Defensive: fetch_users uses OR across vendor + division;
                # without a match in any of the active flag buckets we drop.
                continue

            users_out.append(AssociatedUserEntry(
                id=u.id,
                login=u.login,
                email=u.email,
                full_name=u.full_name,
                matched_organizations=matched_orgs,
                matched_owner_division=matched_owner_div,
                matched_division=matched_div,
            ))

        return AssociatedUsersResponse(users=users_out)

    # ── UI-shaped team-page endpoints ────────────────────────────────────────

    @staticmethod
    def _format_display_name(user_dict: Dict[str, Any]) -> str:
        """'Full Name (login)' — same compact format as USER_DIRECTORY in HTML."""
        parts = (user_dict.get("full_name") or "").strip()
        login = user_dict.get("login", "")
        return f"{parts} ({login})" if parts else login

    def _resolve_uidai_org_id(self) -> Optional[str]:
        """The UIDAI organization's vendor id, resolved by name (it is
        bootstrapped into masters.vendors per environment, so we never hardcode
        the id). Returns None if no live UIDAI vendor exists."""
        return self.db.execute(
            select(Vendor.id)
            .where(func.lower(Vendor.name) == "uidai")
            .where(Vendor.deleted_at.is_(None))
        ).scalars().first()

    def _division_role_candidates(
        self, *, role: str, division_code: Optional[str], authorization: str,
    ) -> List[TeamUserChip]:
        """Bug #226 core: holders of ``role`` whose ``users.division`` equals
        ``division_code`` within the UIDAI organization. Empty when there is no
        division to scope to, or no UIDAI org is configured."""
        if not division_code:
            return []
        uidai_id = self._resolve_uidai_org_id()
        if not uidai_id:
            return []
        rows = self.user_mgmt_client.fetch_users(
            authorization=authorization,
            divisions=[division_code],
            role=role,
            org_id=uidai_id,
        )
        return [
            TeamUserChip(
                id=u["id"],
                login=u.get("login", ""),
                email=u.get("email"),
                full_name=u.get("full_name"),
            )
            for u in rows
            if u.get("id")
        ]

    # ── Bug #226: per-dropdown candidate lists ──────────────────────────────
    # One method per Manage-Team dropdown — the FE calls the matching endpoint
    # and uses the result directly as that dropdown's options. Project-owner
    # pickers resolve the division from the project's owner; activity pickers
    # take the activity's concerned division as ``division_code``.

    def candidates_project_owners(
        self, project_id: str, *, authorization: str = "",
    ) -> List[TeamUserChip]:
        proj = self._get_project_or_404(project_id)
        return self._division_role_candidates(
            role="division_owner", division_code=proj.owner, authorization=authorization,
        )

    def candidates_project_owner_approvers(
        self, project_id: str, *, authorization: str = "",
    ) -> List[TeamUserChip]:
        proj = self._get_project_or_404(project_id)
        return self._division_role_candidates(
            role="division_approver", division_code=proj.owner, authorization=authorization,
        )

    def candidates_activity_members(
        self, project_id: str, *, division_code: str, authorization: str = "",
    ) -> List[TeamUserChip]:
        self._get_project_or_404(project_id)
        return self._division_role_candidates(
            role="division_member", division_code=division_code, authorization=authorization,
        )

    def candidates_activity_approvers(
        self, project_id: str, *, division_code: str, authorization: str = "",
    ) -> List[TeamUserChip]:
        self._get_project_or_404(project_id)
        return self._division_role_candidates(
            role="division_approver", division_code=division_code, authorization=authorization,
        )

    def get_team_page(self, project_id: str, *, authorization: str = "") -> TeamPageResponse:
        """Full UI state for GET /projects/{id}/team-page.

        Returns projectId/projectName, userDirectory (assignable users formatted
        for USER_DIRECTORY), and the three state sections (orgUser, projectOwner,
        activities) with user IDs — not full user objects — matching the JS state
        shape exactly so the frontend needs zero transformation.
        """
        proj = self._get_project_or_404(project_id)

        # userDirectory — assignable users formatted for the user picker
        raw_users = self.assignable_repo.list_assignable_users_for_project(
            project_id, authorization=authorization,
        )
        user_directory = [
            UserDirectoryEntry(id=u["id"], name=self._format_display_name(u))
            for u in raw_users
        ]

        # orgUser — read from user_role_assignments (read-only on this endpoint).
        # Bug #161: always emit BOTH org-user rows in a fixed order
        # (project_admin then project_member), even when one has no users. The
        # FE merges these by array position and ignores roleLabel, so omitting
        # an empty role (or reordering) shifts the other role's users onto the
        # wrong row — making "saved Project Member users" appear under Project
        # Admin (or vanish from the row they were added to).
        org_members = self._read_org_members(project_id)
        users_by_role = {
            bucket.role_name: [c.id for c in bucket.users] for bucket in org_members
        }
        org_user = [
            OrgUserRow(role_label=role_name, users=users_by_role.get(role_name, []))
            for role_name in _ORG_USER_ROLE_ORDER
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

        # ownerDivision / concernedDivisions — resolved against masters.divisions.
        # Hydrate EVERY division code referenced on the page in a single lookup:
        # the project owner + project concerned union, AND each activity's own
        # owner + concerned codes — so the per-activity ownerDivision carries the
        # masters label (id/code/name) just like the project-level one.
        owner_division, concerned_codes = self.associated_repo.get_project_division_codes(
            project_id,
        )
        all_codes = set(concerned_codes)
        if owner_division:
            all_codes.add(owner_division)
        for row in team_activities:
            if row.owner_division:
                all_codes.add(row.owner_division)
            all_codes.update(c for c in (row.concerned_divisions or []) if c)
        division_rows = self.associated_repo.get_divisions_by_codes(sorted(all_codes))

        def _to_ref(code: str) -> DivisionRef:
            d = division_rows.get(code)
            return DivisionRef(
                id=d.id if d else None,
                code=code,
                name=d.label if d else None,
            )

        # Hydrated refs for EVERY referenced code. The FE keeps the per-activity
        # concernedDivisions as bare codes (it keys division-user maps by code),
        # so this list lets it resolve those codes to labels. A list (not a
        # code->label dict) because the wrap layer camelizes dict keys and would
        # mangle codes like 'DIV_X' -> 'DIVX'.
        division_ref_list: List[DivisionRef] = [_to_ref(c) for c in sorted(all_codes)]

        activities = [
            TeamPageActivity(
                id=row.id,
                display_code=row.display_code,
                name=row.name,
                milestone_id=row.milestone_id,
                milestone_display_code=row.milestone_display_code,
                milestone=row.milestone_name,
                owner_division=_to_ref(row.owner_division) if row.owner_division else None,
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

        owner_division_ref: Optional[DivisionRef] = _to_ref(owner_division) if owner_division else None
        concerned_divisions_refs: List[DivisionRef] = [_to_ref(c) for c in concerned_codes]

        return TeamPageResponse(
            project_id=proj.id,
            project_code=proj.project_code,
            project_name=proj.name,
            owner_division=owner_division_ref,
            concerned_divisions=concerned_divisions_refs,
            division_refs=division_ref_list,
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
        authorization: str,
    ) -> TeamPageResponse:
        """Bulk save for PUT /projects/{id}/team-page (the Submit button).

        Flow:
          1. Diff the incoming ``orgUser`` against the current state. If
             any role's user set differs, forward the changed roles to
             user-management's ``PUT /api/v3/projects/{uuid}/role-assignments``
             over HTTP, carrying the caller's JWT verbatim. If that call
             fails, raise ``UserMgmtUnavailableError`` (502) and DO NOT
             touch the local DB.
          2. Persist ``projectOwner`` (single project_ownership rewrite).
          3. Persist every entry in ``activities`` (one activity_assignment
             rewrite per id).
          4. Commit and return the refreshed page state.

        The cross-service call runs BEFORE the local writes so a failed
        upstream call leaves both sides in their pre-call state — no
        partial application across schemas.
        """
        self._get_project_or_404(project_id)

        # ---- 1. orgUser: diff + cross-service write (when needed) -----------
        self._maybe_sync_org_user(
            project_id=project_id,
            requested=payload.org_user,
            authorization=authorization,
        )

        # ---- 2. projectOwner: local write -----------------------------------
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

        # ---- 3. activities: local write -------------------------------------
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

    def _maybe_sync_org_user(
        self,
        *,
        project_id: str,
        requested: List[OrgUserRow],
        authorization: str,
    ) -> None:
        """Diff requested orgUser against current state; call user-mgmt only
        if anything changed.

        Builds two dicts of ``{role_name: set(user_ids)}`` — the requested
        snapshot and the current snapshot — and computes the per-role diff.
        Only roles whose user sets actually differ are forwarded; roles
        identical between requested and current are skipped (user-mgmt's
        bulk-replace leaves unmentioned roles untouched).

        If the caller didn't include ``orgUser`` at all (empty list), no
        upstream call is made — the FE is implicitly saying "leave
        org-user state alone."
        """
        if not requested:
            return

        requested_by_role: Dict[str, set] = {}
        for row in requested:
            role = row.role_label
            requested_by_role.setdefault(role, set()).update(row.users)

        current_by_role: Dict[str, set] = {}
        for bucket in self._read_org_members(project_id):
            current_by_role.setdefault(bucket.role_name, set()).update(
                c.id for c in bucket.users
            )

        roles_to_forward: Dict[str, List[str]] = {}
        for role, req_users in requested_by_role.items():
            cur_users = current_by_role.get(role, set())
            if req_users != cur_users:
                roles_to_forward[role] = sorted(req_users)

        if not roles_to_forward:
            return

        self.user_mgmt_client.replace_project_role_assignments(
            project_uuid=project_id,
            assignments_by_role=roles_to_forward,
            authorization=authorization,
        )
