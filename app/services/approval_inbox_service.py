"""ApprovalInboxService — orchestrates the two Approval Inbox reads.

Responsibilities:
  * Resolve the caller's role + division from the FastAPI ``Request.state``
    (hydrated by ``app.middleware.auth_middleware``).
  * Query ``activity_workflow_tracker`` for rows the caller can act on.
  * Hydrate PMIS-side context (activity, project, vendor name, milestone
    position for display code) from the local DB.
  * Pull the workflow history for detail-view rendering from the Java
    service via ``WorkflowClient``. Falls back to the cached tracker
    state if Java is unreachable.
  * Translate Java vocabulary → FE pill status via
    ``app.utilities.workflow_state``.

Business rules:
  * Caller MUST be authenticated. Admin callers bypass division filters.
  * For ``concerned_division`` role, only tracker rows where the
    caller's division is in ``consent_divisions[]`` AND the state is
    PENDINGATCONCERNEDDIVISION are returned.
  * For ``activity_owner`` role, only tracker rows where the caller's
    division == ``owner_division`` AND state is PENDINGATOWNERDIVISION
    are returned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set, Tuple

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.permissions import APPROVALS_MODERATE
from app.models._cross_schema import User, Vendor
from app.models.activity import Activity
from app.models.activity_workflow_tracker import ActivityWorkflowTracker
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.task import Task
from app.repositories.activity_workflow_tracker_repository import (
    ActivityWorkflowTrackerRepository,
)
from app.schemas.approval_inbox import (
    InboxDetailResponse,
    InboxListResponse,
    InboxRow,
    TransitionRequest,
    _DivisionDecision,
    _InboxActivity,
    _InboxActivityDetail,
    _InboxProject,
    _MyView,
    _OwnerDecision,
    _Submission,
    _SubmissionEntry,
)
from app.services.notification_client import (
    NotificationClient,
    TEMPLATE_APPROVED_BY_DIVISION,
    TEMPLATE_COMPLETED,
    TEMPLATE_REJECTED,
    TEMPLATE_SUBMITTED_TO_DIVISION,
)
from app.services.workflow_client import WorkflowClient, WorkflowServiceError
from app.utilities import workflow_state as wfs
from app.utilities.catalogs import is_terminal_status
from app.utilities.logger import get_logger


logger = get_logger(__name__)


# ── Caller context ─────────────────────────────────────────────────────────

@dataclass
class CallerContext:
    user_id: str
    division: Optional[str]
    role_codes: List[str]
    is_admin: bool
    # §3.1 (2026-06-02 audit) item 4: caller's effective permission codes,
    # used to replace `is_admin` short-circuits in _authorize_detail,
    # _authorize_submit, _authorize_transition. Default empty set so older
    # call sites (still constructing CallerContext positionally) keep
    # working until updated.
    permissions: Set[str] = field(default_factory=set)


class ApprovalInboxService:
    def __init__(self, db: Session):
        self.db = db
        self.tracker_repo = ActivityWorkflowTrackerRepository(db)
        self.client = WorkflowClient()
        self.notify = NotificationClient()

    # ── public entrypoints ───────────────────────────────────────────────

    def list_inbox(
        self,
        request: Request,
        *,
        role: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> InboxListResponse:
        ctx = self._caller_context(request)
        # Derive effective role: explicit param > admin > inferred from data.
        # For the inbox listing we present concerned_division as default for
        # a normal user with a division; admins see all PENDING rows.
        effective_role = self._derive_role(ctx, role)
        states = wfs.states_pending_for_role(effective_role)
        rows = self._fetch_tracker_rows(ctx, effective_role, states)
        # ``status`` is currently advisory (default "pending"); approved/
        # rejected views require historical tracker retention which we
        # defer until the transition proxy is in.
        rows = self._apply_search(rows, search)
        items = [self._build_inbox_row(row, effective_role, ctx) for row in rows]
        return InboxListResponse(total=len(items), items=items)

    def get_detail(
        self, request: Request, business_id: str,
    ) -> InboxDetailResponse:
        ctx = self._caller_context(request)
        tracker = self.tracker_repo.get(business_id)
        if tracker is None:
            raise NotFoundError(
                f"Approval inbox item {business_id} not found",
                code="not_found",
            )
        effective_role = self._derive_role_for_target(ctx, tracker)
        self._authorize_detail(ctx, tracker, effective_role)
        return self._build_detail(ctx, tracker, effective_role)

    def sync(
        self, request: Request, business_id: str,
    ) -> InboxDetailResponse:
        """Reconcile PMIS with the Java workflow's authoritative state for a
        single activity and return the refreshed detail view.

        This is the endpoint the FE calls right after it drives a workflow
        action in the Java service — notably the owner's final APPROVE. It
        finalizes (completes the activity, then rolls the milestone up when
        all its activities are done) when, and ONLY when, the workflow has
        reached its terminal (owner-approved) state. On any non-terminal
        state it just refreshes the cached state and returns. Safe to call
        at any point; idempotent. Authorisation matches the detail read
        (reviewer / owner / approvals-moderator).
        """
        ctx = self._caller_context(request)
        tracker = self.tracker_repo.get(business_id)
        if tracker is None:
            raise NotFoundError(
                f"Approval inbox item {business_id} not found",
                code="not_found",
            )
        effective_role = self._derive_role_for_target(ctx, tracker)
        self._authorize_detail(ctx, tracker, effective_role)
        return self._build_detail(ctx, tracker, effective_role)

    def transition(
        self, request: Request, business_id: str, payload: TransitionRequest,
    ) -> InboxDetailResponse:
        """Proxy a single state transition (SUBMIT / APPROVE / REJECT /
        UPDATE) to the Java workflow service.

        Validates that the caller is allowed to perform the action from
        the current state, posts to Java, updates the local tracker,
        emits the appropriate notification, and returns the refreshed
        detail view so the FE can reflect the new state without an
        extra GET round-trip.
        """
        ctx = self._caller_context(request)
        action = (payload.action or "").strip().upper()
        comment = (payload.comment or "").strip() or None
        if action not in {wfs.ACTION_SUBMIT, wfs.ACTION_APPROVE,
                          wfs.ACTION_REJECT, wfs.ACTION_UPDATE}:
            raise ValidationError(
                f"Unsupported action: {payload.action!r}",
                code="validation_error",
                details={"allowed": ["SUBMIT", "APPROVE", "REJECT", "UPDATE"]},
            )
        if action == wfs.ACTION_REJECT and not comment:
            raise ValidationError(
                "Rejection requires a comment explaining the reason.",
                code="validation_error",
                details={"field": "comment"},
            )

        # SUBMIT creates/refreshes the tracker; everything else requires
        # an existing tracker row.
        if action == wfs.ACTION_SUBMIT:
            tracker = self._handle_submit_pre(business_id, ctx)
        else:
            tracker = self.tracker_repo.get(business_id)
            if tracker is None:
                raise NotFoundError(
                    f"Approval inbox item {business_id} not found",
                    code="not_found",
                )
            self._authorize_transition(ctx, tracker, action)

        # Compute expected next_state locally first so the response is
        # consistent even if Java's response is opaque or in mock mode.
        prev_state = tracker.current_state or wfs.STATE_READY
        new_state = wfs.next_state(prev_state, action) or prev_state

        # ── proxy to Java ──
        try:
            java_resp = self.client.transition(
                business_id=business_id,
                action=action,
                request_info=self._build_request_info(ctx, tracker),
                comment=comment,
            )
        except WorkflowServiceError as exc:
            raise ConflictError(
                f"Workflow service rejected the {action} transition.",
                code="workflow_service_error",
                details=exc.details,
            )
        process_instance_id = self._extract_process_instance_id(java_resp) \
            or tracker.process_instance_id

        # ── update tracker ──
        if action == wfs.ACTION_SUBMIT:
            activity = self.db.get(Activity, tracker.activity_id)
            # IMPORTANT: capture the upserted row — the placeholder
            # ``tracker`` we built in _handle_submit_pre is not bound to
            # the session and has no submitted_at / process_instance_id.
            tracker = self.tracker_repo.upsert_on_submit(
                business_id=business_id,
                activity_id=tracker.activity_id,
                project_id=tracker.project_id,
                process_instance_id=process_instance_id,
                current_state=new_state,
                consent_divisions=list(activity.concerned_divisions or [])
                    if activity else [],
                owner_division=(activity.owner_division if activity else None),
                vendor_id=(activity.vendor_id if activity else None),
                actor_user_id=ctx.user_id,
            )
        else:
            self.tracker_repo.update_state(
                tracker, current_state=new_state,
                process_instance_id=process_instance_id,
                actor_user_id=ctx.user_id,
            )
        # Final-stage owner APPROVE → complete the activity AND roll the
        # milestone up (idempotent — the read/sync path may also finalize).
        if (action == wfs.ACTION_APPROVE
                and prev_state == wfs.STATE_PENDING_OWNER):
            self._finalize_completion(tracker, actor_user_id=ctx.user_id)
        self.db.commit()

        # ── notification dispatch (best-effort, post-commit) ──
        self._dispatch_for_transition(
            tracker, action, prev_state, new_state, comment,
        )

        effective_role = self._derive_role_for_target(ctx, tracker)
        return self._build_detail(ctx, tracker, effective_role)

    # ── detail response builder (shared by get_detail + transition) ──────

    def _build_detail(
        self,
        ctx: CallerContext,
        tracker: ActivityWorkflowTracker,
        effective_role: str,
    ) -> InboxDetailResponse:
        activity, milestone, project, vendor = self._hydrate_pmis_context(tracker)
        history = self._fetch_history_safe(tracker.business_id)
        # Re-sync the local cache from Java's authoritative history and,
        # when the workflow has reached its terminal (owner-approved) state,
        # finalize the activity + roll the milestone up. Idempotent — a
        # no-op when nothing changed or the activity is already completed.
        current_state = self._sync_state_from_java(
            tracker, history, actor_user_id=ctx.user_id,
        )
        self.db.commit()
        submission = self._build_submission(history)
        division_decisions = self._build_division_decisions(tracker, history)
        owner_decision = self._build_owner_decision(history)
        my_view = self._build_my_view(ctx, tracker, effective_role)
        display_code = self._activity_display_code(milestone, activity)
        return InboxDetailResponse(
            business_id=tracker.business_id,
            process_instance_id=tracker.process_instance_id,
            activity=_InboxActivityDetail(
                id=activity.id,
                display_code=display_code,
                name=activity.name,
                description=activity.description,
                planned_start_date=activity.start_date,
                planned_end_date=activity.end_date,
                owner_division=activity.owner_division,
                consent_divisions=list(activity.concerned_divisions or []),
            ),
            project=_InboxProject(
                id=project.id,
                code=getattr(project, "project_code", None),
                name=project.name,
            ),
            organization=(vendor.name if vendor else None),
            submitted_at=tracker.submitted_at,
            submission=submission,
            status=wfs.state_to_pill(current_state),
            division_decisions=division_decisions,
            owner_decision=owner_decision,
            my_view=my_view,
        )

    # ── caller / role helpers ────────────────────────────────────────────

    def _caller_context(self, request: Request) -> CallerContext:
        uid = getattr(request.state, "user_id", None)
        if not uid:
            raise UnauthorizedError(
                "Authentication required", code="auth_required",
            )
        is_admin = bool(getattr(request.state, "is_admin", False))
        # Caller division lives on the users mirror.
        division = self._caller_division(uid)
        roles = self._caller_role_codes(uid)
        perms = getattr(request.state, "user_permissions", None) or set()
        return CallerContext(
            user_id=uid, division=division, role_codes=roles,
            is_admin=is_admin, permissions=set(perms),
        )

    def _caller_division(self, user_id: str) -> Optional[str]:
        row = self.db.execute(
            select(User.division)
            .where(User.id == user_id)
            .where(User.deleted_at.is_(None))
        ).first()
        return row[0] if row else None

    def _caller_role_codes(self, user_id: str) -> List[str]:
        # PMIS stores role memberships in TWO places:
        #   * users.user_roles                — global role memberships
        #                                       (admin, super_admin, test_role).
        #   * users.user_role_assignments     — scoped role assignments
        #                                       (project_admin, project_member,
        #                                        org_admin, division_member).
        # We union the role names from both so the caller's "is this
        # user a project_admin?" check works regardless of which table
        # holds the grant.
        from app.models._cross_schema import (
            Role, UserRole, UserRoleAssignment,
        )
        rows_global = self.db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        ).all()
        rows_scoped = self.db.execute(
            select(Role.name)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
        ).all()
        names = {r[0] for r in (rows_global + rows_scoped) if r and r[0]}
        return sorted(names)

    def _derive_role(
        self, ctx: CallerContext, explicit_role: Optional[str],
    ) -> str:
        """Decide which inbox view to render."""
        if explicit_role:
            return explicit_role.strip().lower()
        if ctx.is_admin:
            return "admin"
        # Default for users with a division → concerned-division view.
        # Owner-view callers will pass ``role=activity_owner`` explicitly,
        # or be served via separate UI buckets later. Both views can be
        # supported simultaneously by issuing two requests; we don't try
        # to merge them server-side.
        return "concerned_division"

    def _derive_role_for_target(
        self, ctx: CallerContext, tracker: ActivityWorkflowTracker,
    ) -> str:
        if ctx.is_admin:
            return "admin"
        my_div = (ctx.division or "").lower()
        if my_div and my_div == (tracker.owner_division or "").lower():
            return "activity_owner"
        consent = [str(d).lower() for d in (tracker.consent_divisions or [])]
        if my_div and my_div in consent:
            return "concerned_division"
        return "viewer"

    def _authorize_detail(
        self, ctx: CallerContext, tracker: ActivityWorkflowTracker, role: str,
    ) -> None:
        # §3.1 item 4: replaced ctx.is_admin with APPROVALS_MODERATE check.
        if APPROVALS_MODERATE in ctx.permissions:
            return
        if role in ("concerned_division", "activity_owner"):
            return
        raise ForbiddenError(
            "Caller is not a reviewer for this approval request",
            code="permission_denied",
        )

    # ── tracker fetch + filtering ────────────────────────────────────────

    def _fetch_tracker_rows(
        self,
        ctx: CallerContext,
        role: str,
        states: Iterable[str],
    ) -> List[ActivityWorkflowTracker]:
        if role == "admin" or ctx.is_admin:
            return self.tracker_repo.list_all_live(states=states)
        if not ctx.division:
            # No division → nothing to show in either division view.
            return []
        if role == "activity_owner":
            return self.tracker_repo.list_for_owner_division(
                division_code=ctx.division, states=states,
            )
        # Default: concerned-division view.
        return self.tracker_repo.list_for_concerned_division(
            division_code=ctx.division, states=states,
        )

    @staticmethod
    def _apply_search(
        rows: List[ActivityWorkflowTracker], q: Optional[str],
    ) -> List[ActivityWorkflowTracker]:
        if not q:
            return rows
        # Search is a thin filter on the already-fetched set so we don't
        # rebuild the SQL. With pending inboxes typically small (tens of
        # rows), this is fine. If volume grows, push into the repo.
        needle = q.strip().lower()
        if not needle:
            return rows
        kept: List[ActivityWorkflowTracker] = []
        for r in rows:
            haystack = " ".join(filter(None, [
                r.business_id, r.activity_id, r.project_id,
                (r.owner_division or ""),
                " ".join(r.consent_divisions or []),
            ])).lower()
            if needle in haystack:
                kept.append(r)
        return kept

    # ── PMIS hydration ───────────────────────────────────────────────────

    def _hydrate_pmis_context(
        self, tracker: ActivityWorkflowTracker,
    ) -> Tuple[Activity, Optional[Milestone], Project, Optional[Vendor]]:
        activity = self.db.get(Activity, tracker.activity_id)
        if activity is None or activity.deleted_at is not None:
            raise NotFoundError(
                f"Activity {tracker.activity_id} not found", code="not_found",
            )
        milestone = self.db.get(Milestone, activity.milestone_id)
        project = self.db.get(Project, tracker.project_id)
        if project is None or project.deleted_at is not None:
            raise NotFoundError(
                f"Project {tracker.project_id} not found", code="not_found",
            )
        vendor: Optional[Vendor] = None
        if tracker.vendor_id:
            vendor = self.db.get(Vendor, tracker.vendor_id)
        return activity, milestone, project, vendor

    @staticmethod
    def _activity_display_code(
        milestone: Optional[Milestone], activity: Activity,
    ) -> Optional[str]:
        if milestone is None or milestone.position is None:
            return None
        if activity.position is None:
            return None
        return f"A{milestone.position}.{activity.position}"

    # ── inbox row build ──────────────────────────────────────────────────

    def _build_inbox_row(
        self,
        tracker: ActivityWorkflowTracker,
        role: str,
        ctx: CallerContext,
    ) -> InboxRow:
        activity = self.db.get(Activity, tracker.activity_id)
        milestone = self.db.get(Milestone, activity.milestone_id) if activity else None
        project = self.db.get(Project, tracker.project_id)
        vendor = self.db.get(Vendor, tracker.vendor_id) if tracker.vendor_id else None
        return InboxRow(
            business_id=tracker.business_id,
            process_instance_id=tracker.process_instance_id,
            activity=_InboxActivity(
                id=activity.id if activity else tracker.activity_id,
                display_code=self._activity_display_code(milestone, activity)
                    if activity else None,
                name=activity.name if activity else "",
            ),
            project=_InboxProject(
                id=project.id if project else tracker.project_id,
                code=getattr(project, "project_code", None) if project else None,
                name=project.name if project else "",
            ),
            organization=(vendor.name if vendor else None),
            submitted_at=tracker.submitted_at,
            status=wfs.state_to_pill(tracker.current_state),
        )

    # ── Java history → display fields ────────────────────────────────────

    def _fetch_history_safe(self, business_id: str) -> List[dict]:
        try:
            return self.client.search_history(business_id)
        except WorkflowServiceError as exc:
            logger.warning(
                "Workflow service unavailable for %s; using cached state. (%s)",
                business_id, exc.message,
            )
            return []

    @staticmethod
    def _resolve_current_state(
        history: List[dict], fallback: str,
    ) -> str:
        if not history:
            return fallback
        # Java's response orders earliest → latest; take the last entry's
        # (previousStatus, action) and resolve to the resulting state.
        last = history[-1]
        prev = (last.get("previousStatus") or "").upper()
        action = (last.get("action") or "").upper()
        resolved = wfs.next_state(prev, action)
        return resolved or fallback

    def _sync_state_from_java(
        self,
        tracker: ActivityWorkflowTracker,
        history: List[dict],
        *,
        actor_user_id: Optional[str] = None,
    ) -> str:
        """Reconcile the local tracker with Java's authoritative state and,
        when the workflow has reached its terminal (owner-approved) state,
        finalize the activity + milestone roll-up.

        Does NOT commit — the caller owns the transaction boundary.

        In real mode the resolved state comes from Java's ``_search``
        history; in mock mode the local tracker stays authoritative (the
        synthetic history would otherwise clobber test-/proxy-written
        state). The finalize gate (``is_terminal_workflow_state``) is applied
        in BOTH modes so the transition-proxy path and the explicit sync
        path behave identically. Returns the resolved current state.
        """
        if self.client.mode == "real":
            current_state = self._resolve_current_state(
                history, tracker.current_state,
            )
            if current_state and current_state != tracker.current_state:
                self.tracker_repo.update_state(tracker, current_state=current_state)
        else:
            current_state = tracker.current_state
        if wfs.is_terminal_workflow_state(current_state):
            self._finalize_completion(tracker, actor_user_id=actor_user_id)
        return current_state

    @staticmethod
    def _build_submission(history: List[dict]) -> _Submission:
        # "Organization Submission" = the comment(s) on SUBMIT transitions.
        # Re-SUBMITs after rejection appear as additional SUBMIT entries —
        # we surface ALL of them in chronological order so the reviewer
        # sees the full thread.
        submits = [h for h in history if (h.get("action") or "").upper() == "SUBMIT"]
        entries: List[_SubmissionEntry] = []
        for h in submits:
            audit = h.get("auditDetails") or {}
            created_time = audit.get("createdTime")
            when = None
            if created_time:
                # Java sends epoch millis. Convert to UTC datetime.
                from datetime import datetime, timezone
                try:
                    when = datetime.fromtimestamp(
                        int(created_time) / 1000.0, tz=timezone.utc,
                    )
                except (ValueError, OverflowError, OSError):
                    when = None
            entries.append(_SubmissionEntry(
                who=audit.get("createdBy"),
                when=when,
                text=h.get("comment") or None,
                attachments=[],
            ))
        return _Submission(comments=entries)

    @staticmethod
    def _build_division_decisions(
        tracker: ActivityWorkflowTracker, history: List[dict],
    ) -> List[_DivisionDecision]:
        """Render the Division Status grid the Activity-Owner inbox shows.

        In Model A (single-approval) Java tracks ONE concerned-division
        APPROVE event, not one-per-division. So we synthesize the per-
        division rows: every division in the snapshot ``consent_divisions``
        is rendered; the row that the single APPROVE event came from
        (if discernible) is marked approved, the rest as pending — or
        all marked approved once the state has moved past the
        concerned-division stage.
        """
        consent = list(tracker.consent_divisions or [])
        if not consent:
            return []
        # Has the concerned-division stage already cleared?
        state = (tracker.current_state or "").upper()
        cleared = state in (
            wfs.STATE_PENDING_OWNER, wfs.STATE_APPROVED, wfs.STATE_COMPLETED,
        )
        # Find the APPROVE at the concerned-division stage (Model A: at
        # most one such event per workflow round). We use it to source
        # the reviewer attribution; the division attribution is best-
        # effort since Java doesn't tag actions with a division.
        concerned_approves = [
            h for h in history
            if (h.get("action") or "").upper() == "APPROVE"
            and (h.get("previousStatus") or "").upper()
                == wfs.STATE_PENDING_CONCERNED
        ]
        approve_meta = concerned_approves[-1] if concerned_approves else None
        decisions: List[_DivisionDecision] = []
        for div in consent:
            decided_by = None
            decided_at = None
            comment = None
            if cleared:
                row_status = "approved"
                if approve_meta:
                    audit = approve_meta.get("auditDetails") or {}
                    decided_by = audit.get("createdBy")
                    created_time = audit.get("createdTime")
                    if created_time:
                        from datetime import datetime, timezone
                        try:
                            decided_at = datetime.fromtimestamp(
                                int(created_time) / 1000.0, tz=timezone.utc,
                            )
                        except (ValueError, OverflowError, OSError):
                            decided_at = None
                    comment = approve_meta.get("comment") or None
            elif state == wfs.STATE_REJECTED:
                row_status = "rejected"
            else:
                row_status = "pending"
            decisions.append(_DivisionDecision(
                division=str(div),
                status=row_status,
                decided_by=decided_by,
                decided_at=decided_at,
                comment=comment,
            ))
        return decisions

    @staticmethod
    def _build_owner_decision(history: List[dict]) -> Optional[_OwnerDecision]:
        owner_events = [
            h for h in history
            if (h.get("previousStatus") or "").upper() == wfs.STATE_PENDING_OWNER
        ]
        if not owner_events:
            return None
        last = owner_events[-1]
        action = (last.get("action") or "").upper()
        if action == "APPROVE":
            status = "approved"
        elif action == "REJECT":
            status = "rejected"
        else:
            status = "pending"
        audit = last.get("auditDetails") or {}
        decided_at = None
        created_time = audit.get("createdTime")
        if created_time:
            from datetime import datetime, timezone
            try:
                decided_at = datetime.fromtimestamp(
                    int(created_time) / 1000.0, tz=timezone.utc,
                )
            except (ValueError, OverflowError, OSError):
                decided_at = None
        return _OwnerDecision(
            status=status,
            decided_by=audit.get("createdBy"),
            decided_at=decided_at,
            comment=last.get("comment") or None,
        )

    @staticmethod
    def _build_my_view(
        ctx: CallerContext,
        tracker: ActivityWorkflowTracker,
        role: str,
    ) -> _MyView:
        state = tracker.current_state or ""
        if role in ("concerned_division", "activity_owner"):
            pending_for_me = wfs.is_state_pending_for_role(state, role)
        else:
            pending_for_me = False
        if pending_for_me:
            my_status = "pending"
            can_act = True
        else:
            my_status = wfs.state_to_pill(state)
            can_act = ctx.is_admin
        return _MyView(
            role=role,
            my_division=ctx.division,
            my_status=my_status,
            can_approve=can_act,
            can_reject=can_act,
        )

    # ── transition helpers ───────────────────────────────────────────────

    def _handle_submit_pre(
        self,
        business_id: str,
        ctx: CallerContext,
    ) -> ActivityWorkflowTracker:
        """Pre-flight checks for SUBMIT.

        Verifies the activity exists, validates the state-machine
        position (not already in a non-terminal workflow), and confirms
        every live task is completed (or the activity has no tasks).
        Returns the existing tracker row when present (so re-SUBMIT
        after REJECT/UPDATE refreshes the snapshot), or a synthetic
        placeholder when this is the first submit — the actual upsert
        happens after Java confirms the transition.
        """
        activity = self.db.get(Activity, business_id)
        if activity is None or activity.deleted_at is not None:
            raise NotFoundError(
                f"Activity {business_id} not found", code="not_found",
            )
        self._authorize_submit(ctx, activity)
        self._assert_activity_ready_for_submit(activity)
        existing = self.tracker_repo.get(business_id)
        if existing is not None:
            # Re-SUBMIT after UPDATE / REJECT — block if already mid-
            # flight in a pending state (would orphan reviewer slots).
            blocked = {
                wfs.STATE_PENDING_CONCERNED,
                wfs.STATE_PENDING_OWNER,
                wfs.STATE_APPROVED,
                wfs.STATE_COMPLETED,
            }
            if (existing.current_state or "").upper() in blocked:
                raise ConflictError(
                    "Activity workflow is already in progress.",
                    code="workflow_in_progress",
                    details={"current_state": existing.current_state},
                )
            return existing
        # Synthetic placeholder so callers that read `tracker.activity_id`
        # before the upsert get the correct linkage. NOT persisted —
        # ``upsert_on_submit`` runs after Java responds.
        placeholder = ActivityWorkflowTracker(
            business_id=business_id,
            activity_id=activity.id,
            project_id=activity.project_id,
            current_state=wfs.STATE_READY,
            consent_divisions=list(activity.concerned_divisions or []),
            owner_division=activity.owner_division,
            vendor_id=activity.vendor_id,
        )
        return placeholder

    def _authorize_submit(
        self, ctx: CallerContext, activity: Activity,
    ) -> None:
        """SUBMIT requires the caller to be either an approvals-moderator
        or the activity vendor (organization). Project_admin role is also
        allowed since the Postman reject collection's UPDATE→SUBMIT
        sample uses PROJECT_ADMIN."""
        # §3.1 item 4: replaced ctx.is_admin with APPROVALS_MODERATE check.
        if APPROVALS_MODERATE in ctx.permissions:
            return
        role_set = {r.lower() for r in (ctx.role_codes or [])}
        if {"project_admin", "super_admin", "admin"} & role_set:
            return
        # Caller belongs to the activity's vendor org?
        caller_vendor = self._caller_vendor_id(ctx.user_id)
        if caller_vendor and activity.vendor_id and caller_vendor == activity.vendor_id:
            return
        raise ForbiddenError(
            "Only the activity vendor or a project admin can submit "
            "this activity for approval.",
            code="permission_denied",
        )

    def _authorize_transition(
        self,
        ctx: CallerContext,
        tracker: ActivityWorkflowTracker,
        action: str,
    ) -> None:
        """Validate caller permission for APPROVE / REJECT / UPDATE."""
        # §3.1 item 4: replaced ctx.is_admin with APPROVALS_MODERATE check.
        if APPROVALS_MODERATE in ctx.permissions:
            return
        state = (tracker.current_state or "").upper()
        my_div = (ctx.division or "").lower()
        consent = [str(d).lower() for d in (tracker.consent_divisions or [])]
        owner_div = (tracker.owner_division or "").lower()
        role_set = {r.lower() for r in (ctx.role_codes or [])}

        if action == wfs.ACTION_UPDATE:
            # Update is the vendor's "edit and resubmit" step.
            caller_vendor = self._caller_vendor_id(ctx.user_id)
            if (caller_vendor and tracker.vendor_id
                    and caller_vendor == tracker.vendor_id):
                return
            if {"project_admin", "super_admin", "admin"} & role_set:
                return
            raise ForbiddenError(
                "Only the activity vendor can UPDATE a rejected request.",
                code="permission_denied",
            )

        if action in (wfs.ACTION_APPROVE, wfs.ACTION_REJECT):
            if state == wfs.STATE_PENDING_CONCERNED:
                if my_div and my_div in consent:
                    return
                raise ForbiddenError(
                    "Caller's division is not among this activity's consent "
                    "divisions.",
                    code="permission_denied",
                )
            if state == wfs.STATE_PENDING_OWNER:
                if my_div and my_div == owner_div:
                    return
                raise ForbiddenError(
                    "Caller's division is not the activity's owner division.",
                    code="permission_denied",
                )
            raise ConflictError(
                f"Action {action} is not valid from state {state}.",
                code="invalid_transition",
                details={"state": state, "action": action},
            )

    def _assert_activity_ready_for_submit(self, activity: Activity) -> None:
        """Every live task under the activity must be completed (or the
        activity must have no tasks). Matches the FE's "last task
        complete → start workflow" pre-condition."""
        rows = list(self.db.execute(
            select(Task.status)
            .where(Task.activity_id == activity.id)
            .where(Task.deleted_at.is_(None))
        ).all())
        if rows and not all(is_terminal_status(s) for (s,) in rows):
            raise ConflictError(
                "Activity has incomplete tasks; cannot submit for approval.",
                code="tasks_incomplete",
            )

    def _caller_vendor_id(self, user_id: str) -> Optional[str]:
        row = self.db.execute(
            select(User.vendor_id)
            .where(User.id == user_id)
            .where(User.deleted_at.is_(None))
        ).first()
        return row[0] if row else None

    def _build_request_info(
        self, ctx: CallerContext, tracker: ActivityWorkflowTracker,
    ) -> dict:
        """Assemble the DIGIT-style RequestInfo block expected by Java."""
        my_div = (ctx.division or "").lower()
        consent = [str(d).lower() for d in (tracker.consent_divisions or [])]
        owner_div = (tracker.owner_division or "").lower()
        is_concerned = bool(my_div) and my_div in consent
        is_owner = bool(my_div) and my_div == owner_div
        java_roles = wfs.build_java_roles(
            pmis_role_codes=ctx.role_codes,
            is_concerned_division=is_concerned,
            is_owner_division=is_owner,
        )
        user_row = self.db.execute(
            select(User).where(User.id == ctx.user_id)
        ).scalar_one_or_none()
        login = (user_row.login if user_row else ctx.user_id)
        full_name = (user_row.full_name if user_row else None) or login
        return {
            "authToken": "",  # Java accepts empty when network is trusted (dev).
            "userInfo": {
                "uuid": ctx.user_id,
                "userName": login,
                "name": full_name,
                "type": "EMPLOYEE",
                "roles": java_roles,
            },
        }

    @staticmethod
    def _extract_process_instance_id(java_resp: dict) -> Optional[str]:
        instances = (java_resp or {}).get("ProcessInstances") or []
        if not instances:
            return None
        return instances[0].get("id") or None

    def _finalize_completion(
        self, tracker: ActivityWorkflowTracker,
        *, actor_user_id: Optional[str] = None,
    ) -> None:
        """Complete the PMIS activity + roll the milestone up when the
        approval workflow has reached its terminal (owner-approved) state.

        Delegates to ``ActivityService.complete_from_workflow`` so the
        status flip, audit row, and milestone/project roll-up all reuse the
        canonical cascade rather than being re-implemented here. Idempotent
        and best-effort — a no-op when the activity is already completed,
        deleted, or missing.
        """
        from app.services.activity_service import ActivityService
        activity = self.db.get(Activity, tracker.activity_id)
        if activity is None or activity.deleted_at is not None:
            return
        ActivityService(self.db).complete_from_workflow(
            activity, caller_user_id=actor_user_id,
        )

    # ── notification dispatch ────────────────────────────────────────────

    def _dispatch_for_transition(
        self,
        tracker: ActivityWorkflowTracker,
        action: str,
        prev_state: str,
        new_state: str,
        comment: Optional[str],
    ) -> None:
        """Send the right template based on the transition outcome.

        All sends are best-effort: a failing notification will not roll
        back the transition (notification client logs the failure and
        returns False).
        """
        try:
            activity = self.db.get(Activity, tracker.activity_id)
            project = self.db.get(Project, tracker.project_id)
            vendor = (self.db.get(Vendor, tracker.vendor_id)
                      if tracker.vendor_id else None)
            base_payload = {
                "businessId": tracker.business_id,
                "activityName": (activity.name if activity else ""),
                "projectName": (project.name if project else ""),
                "organization": (vendor.name if vendor else ""),
                "comment": comment or "",
            }
            if action == wfs.ACTION_SUBMIT \
                    and new_state == wfs.STATE_PENDING_CONCERNED:
                emails = self._emails_for_divisions(tracker.consent_divisions)
                self.notify.dispatch_many(
                    emails,
                    template_kind=TEMPLATE_SUBMITTED_TO_DIVISION,
                    payload=base_payload,
                )
                return
            if action == wfs.ACTION_APPROVE \
                    and prev_state == wfs.STATE_PENDING_CONCERNED:
                emails = self._emails_for_divisions(
                    [tracker.owner_division] if tracker.owner_division else [],
                )
                self.notify.dispatch_many(
                    emails,
                    template_kind=TEMPLATE_APPROVED_BY_DIVISION,
                    payload=base_payload,
                )
                return
            if action == wfs.ACTION_APPROVE \
                    and prev_state == wfs.STATE_PENDING_OWNER:
                if vendor and vendor.email:
                    self.notify.dispatch(
                        user_id=None, channel="email",
                        recipient=vendor.email,
                        template_kind=TEMPLATE_COMPLETED,
                        payload=base_payload,
                    )
                return
            if action == wfs.ACTION_REJECT:
                if vendor and vendor.email:
                    self.notify.dispatch(
                        user_id=None, channel="email",
                        recipient=vendor.email,
                        template_kind=TEMPLATE_REJECTED,
                        payload=base_payload,
                    )
                return
            # UPDATE doesn't notify — the subsequent SUBMIT will.
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("Notification dispatch raised: %s", exc)

    def _emails_for_divisions(self, divisions: Iterable[str]) -> List[str]:
        """Resolve user emails for a set of division codes via the User
        mirror. Empty divisions list → empty result."""
        divs = [str(d).lower() for d in (divisions or []) if d]
        if not divs:
            return []
        rows = self.db.execute(
            select(User.email)
            .where(User.deleted_at.is_(None))
            .where(User.email.isnot(None))
            .where(User.division.in_(divs))
        ).all()
        return [r[0] for r in rows if r and r[0]]
