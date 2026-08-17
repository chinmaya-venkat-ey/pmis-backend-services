"""MilestoneService — CRUD + position management + dependency cycle guard.

Inline-create contract: ``create`` writes the milestone row, optionally
followed (in the same DB transaction) by a comment row carrying inline
body and/or file attachments. The attachments list is the JSONB envelope
the route layer built from either the JSON request body or the multipart
files via the file client.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

# FE normalizes node.id to the WBS display code (e.g. "M1") after
# normalizeProject runs, so depends_on arrives as display codes rather
# than UUIDs. Bug #6: resolve them back to UUIDs via the position column.
_MILESTONE_DISPLAY_CODE_RE = re.compile(r"^M(\d+)$", re.IGNORECASE)

from sqlalchemy.orm import Session

from datetime import datetime
from decimal import Decimal

from app.core.errors import (
    ConflictError,
    DependencyCycleError,
    MilestoneNotFoundError,
    ProjectNotFoundError,
    ValidationError,
)
from app.repositories.activity_repository import ActivityRepository
from app.repositories.comment_repository import CommentRepository
from app.repositories.finance_repository import FinanceRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.milestone import MilestoneCreateRequest, MilestoneUpdateRequest
from app.utilities import ccn_calc
from app.utilities.catalogs import (
    active_milestone_statuses,
    active_payment_types,
    active_priorities,
    is_known_milestone_status,
    is_known_payment_type,
    is_known_priority,
    is_terminal_status,
)
from app.utilities.date_rules import IST, to_ist_calendar_date, validate_entity_dates
from app.utilities.project_lock import assert_milestone_activity_writable
from app.utilities.quarter_windows import quarter_window_of, quarter_windows
from app.utilities.required_fields import assert_required_not_cleared
from app.utilities.vendor_resolver import resolve_and_validate_vendor_ids


# Doc-finance: category choices for milestone / activity rows.
_CATEGORY_ORIGINAL = "original"
_CATEGORY_ASG = "asg"
_CATEGORY_CCN = "ccn"
_VALID_CATEGORIES = (_CATEGORY_ORIGINAL, _CATEGORY_ASG, _CATEGORY_CCN)


def _ist_midnight(d) -> datetime:
    """A quarter-window ``date`` as an IST-midnight tz-aware ``datetime`` —
    activities store tz-aware ``start_date``/``end_date`` and the rest of the
    stack compares on the IST calendar date."""
    return datetime(d.year, d.month, d.day, tzinfo=IST)


class MilestoneService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MilestoneRepository(db)
        self.projects = ProjectRepository(db)
        self.comments = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)
        self.finance = FinanceRepository(db)
        self.activities = ActivityRepository(db)

    # ------------------------------------------------------------------ read

    def get_by_id(self, milestone_id: str, *, caller_vendor_id=None, caller_is_admin: bool = True):
        row = self.repo.get_by_id(milestone_id)
        if row is None:
            raise MilestoneNotFoundError("The milestone could not be found.")
        # Vendor scoping: a vendor user may only see a milestone their org has a
        # live activity on. Hide others as 404 (don't reveal existence).
        from app.core.milestone_scope import can_see_milestone
        if not can_see_milestone(
            self.db, row, caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin
        ):
            raise MilestoneNotFoundError("The milestone could not be found.")
        return row

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
        caller_vendor_id=None, caller_is_admin: bool = True,
    ):
        return self.repo.list_for_project(
            project_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
            caller_vendor_id=caller_vendor_id, caller_is_admin=caller_is_admin,
        )

    # ------------------------------------------------------------------ write

    def create(  # NOSONAR(S3776): sequential validation gates with order-sensitive side effects (validate -> mutate -> audit -> commit -> depends_on cycle-check) -- refactor deferred to a sprint with FE regression coverage
        self,
        project_id: str,
        payload: MilestoneCreateRequest,
        *,
        caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        project = self.projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError("The project could not be found.")
        # Project must be live and writable (monolith ``project_lock.py``).
        assert_milestone_activity_writable(project)
        # Closed projects are frozen: no new milestones until reopened.
        # (Pairs with the new ``POST /projects/{id}/reopen`` endpoint.)
        if (getattr(project, "status", None) or "").lower() == "closed":
            raise ValidationError(
                "Project is closed. Reopen project first to add milestones.",
                details={"project_id": project_id, "project_status": "closed"},
            )
        # Project must have a start date — milestone dates floor against it.
        if project.start_date is None:
            raise ValidationError(
                "The project does not have a start date yet. Please set "
                "the project start date before adding milestones."
            )
        # Schema-level field_validator handles status (2-value hardcoded
        # set per monolith parity) and priority (uppercase normalize).
        # Service-level catalog checks are skipped — monolith uses the
        # same 2-value list, not the broader transitions catalog.
        self._validate_priority(payload.priority)
        self._validate_payment_type(payload.payment_type)
        # Vendor IDs: monolith parity — silently drop unknown / not-on-
        # project entries (don't raise). The resolved set is persisted on
        # the project_vendors mapping for the milestone but ``vendors`` on
        # the response stays empty (matches monolith milestone shape).
        canonical_vendor_ids = []
        if payload.vendor_ids:
            try:
                canonical_vendor_ids = resolve_and_validate_vendor_ids(
                    self.db, payload.vendor_ids,
                )
            except Exception:
                canonical_vendor_ids = []
        # Date rules — parent floor is the owning project (monolith parity).
        validate_entity_dates(
            entity_start=payload.start_date,
            entity_end=payload.end_date,
            actual_start=payload.actual_start_date,
            actual_end=payload.actual_end_date,
            parent_start_date=project.start_date,
            project_start_date=project.start_date,
            entity_label="milestone",
            parent_label="project",
        )
        # Position always server-assigned (append) — see TaskService.create.
        position = self.repo.next_position_for_project(project_id)
        # Doc-finance: resolve category + ccn_value based on project state.
        category, ccn_value = self._resolve_create_category(
            project=project,
            requested_category=payload.category,
            requested_ccn_value=payload.ccn_value,
        )
        row = self.repo.create(
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            actual_start_date=payload.actual_start_date,
            actual_end_date=payload.actual_end_date,
            status=payload.status or "not_completed",
            priority=payload.priority,
            payment_type=payload.payment_type,
            position=position,
            category=category,
            ccn_value=ccn_value,
            is_resource_based=payload.is_resource_based,
            is_transaction_based=payload.is_transaction_based,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if payload.depends_on:
            resolved_deps = self._resolve_depends_on(project_id, payload.depends_on)
            self._guard_dependency_cycle(row.id, resolved_deps)
            self._assert_deps_exist(resolved_deps)
            self._assert_dep_dates_outlasting(row, resolved_deps)
            self.repo.replace_dependencies(row.id, resolved_deps)
        if canonical_vendor_ids:
            self.repo.set_vendor_mapping(row.id, canonical_vendor_ids)

        # Inline comment / attachments — written under the new milestone.
        # Capture the created comment row on a transient ``_inline_comment``
        # attribute so the controller can echo it back on the multipart
        # create response (monolith parity — ``data.comment: {...}``).
        body_clean = (body or "").strip() or None
        atts = list(attachments or [])
        row._inline_comment = None
        if body_clean or atts:
            row._inline_comment = self.comments.create(
                target_kind="milestone",
                target_id=row.id,
                author_user_id=caller_user_id,
                body=body_clean,
                attachments=atts or None,
            )

        self.audit.write(
            project_id=project_id,
            target_kind="milestone", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "position": row.position},
        )
        # Doc-finance: dedicated audit entry for post-publish ASG / CCN
        # creates so the lineage is searchable separately from the
        # generic ``create`` event.
        if row.category == _CATEGORY_CCN:
            self.audit.write(
                project_id=project_id,
                target_kind="milestone", target_id=row.id,
                action="create_ccn", actor_user_id=caller_user_id,
                changes={
                    "ccn_value": str(row.ccn_value),
                    "ccn_cap_amount": str(
                        ccn_calc.ccn_cap_amount(
                            project.total_project_value_excl_tax,
                            project.ccn_cap_percent,
                        )
                    ),
                },
            )
        elif row.category == _CATEGORY_ASG:
            self.audit.write(
                project_id=project_id,
                target_kind="milestone", target_id=row.id,
                action="create_asg", actor_user_id=caller_user_id,
                changes={"category": _CATEGORY_ASG},
            )
        # Resource-based auto-tiler: lay the phase out as one activity per
        # anchored quarter so its SLA quarters line up 1:1 with contract's
        # phase-anchored settlement grid (idempotent — see the helper).
        if row.is_resource_based:
            self._autogenerate_quarter_activities(row, caller_user_id=caller_user_id)
        self.db.commit()
        return row

    def _autogenerate_quarter_activities(self, milestone, *, caller_user_id):
        """Tile a resource-based milestone's ``[start_date, end_date]`` into one
        activity per anchored quarter (``quarter_windows``), named ``Q1``,
        ``Q2`` … so the phase's activities distribute one-per-quarter with no
        gaps — matching contract-management's phase-anchored SLA quarters.

        Runs inside the caller's open transaction (no commit of its own).
        Idempotent no-op when the milestone is not resource-based, is missing
        either date, or already has ANY live activity — so an existing
        milestone whose activities carry SLA mappings is never regenerated
        here (that is the realign endpoint's job). Generated activities carry
        no resource allocations; the user fills those in later and each
        allocation's ``duration`` then follows its activity's quarter window.
        Returns the created rows (``[]`` when it no-ops)."""
        if not getattr(milestone, "is_resource_based", False):
            return []
        windows = quarter_windows(milestone.start_date, milestone.end_date)
        if not windows:
            return []
        # Never clobber existing (possibly SLA-mapped) activities.
        if self.activities.list_by_milestone_ids([milestone.id]):
            return []
        base_position = self.activities.next_position_for_milestone(milestone.id)
        created = []
        for idx, (ws, we) in enumerate(windows):
            row = self.activities.create(
                project_id=milestone.project_id,
                milestone_id=milestone.id,
                name=f"Q{idx + 1}",
                description=None,
                start_date=_ist_midnight(ws),
                end_date=_ist_midnight(we),
                actual_start_date=None,
                actual_end_date=None,
                status="not_completed",
                activity_started=False,
                priority=None,
                owner_division=None,
                concerned_divisions=None,
                vendor_id=None,
                position=base_position + idx,
                category=milestone.category,
                ccn_value=milestone.ccn_value,
                created_by=caller_user_id,
                updated_by=caller_user_id,
            )
            self.audit.write(
                project_id=milestone.project_id,
                target_kind="activity", target_id=row.id,
                action="create", actor_user_id=caller_user_id,
                changes={
                    "name": row.name,
                    "milestone_id": milestone.id,
                    "auto_generated": "resource_quarter",
                },
            )
            created.append(row)
        return created

    def realign_resource_activities(self, milestone_id: str, *, caller_user_id):
        """Snap an EXISTING resource-based milestone's activities onto its
        anchored quarter windows WITHOUT regenerating them.

        Every activity row (id / position), its ``activity_planned_resources``
        allocations, and the contract SLA mappings that reference it are
        preserved — only dates move: each activity's ``[start_date, end_date]``
        is snapped to the quarter window that currently CONTAINS its start
        (``quarter_window_of`` — no reordering, no cross-quarter jumps), and any
        allocation whose ``planned_deployment_date`` then falls outside the new
        window is clamped back into it. Idempotent: once aligned, re-running
        changes nothing. Returns a summary ``{milestone_id, realigned: [...]}``.
        """
        milestone = self.get_by_id(milestone_id)
        if not milestone.is_resource_based:
            raise ValidationError(
                "Only resource-based milestones can have their activities realigned."
            )
        if milestone.start_date is None or milestone.end_date is None:
            raise ValidationError(
                "The milestone needs a start and end date before its activities "
                "can be realigned."
            )
        project = self.projects.get_by_id(milestone.project_id)
        assert_milestone_activity_writable(project)
        activities = self.activities.list_by_milestone_ids(
            [milestone_id]
        ).get(milestone_id, [])
        realigned = []
        for act in activities:
            window = quarter_window_of(
                act.start_date, milestone.start_date, milestone.end_date,
            )
            if window is None:
                continue
            ws, we = window
            change: dict = {}
            if to_ist_calendar_date(act.start_date) != ws:
                change["start_date"] = {
                    "before": to_ist_calendar_date(act.start_date).isoformat(),
                    "after": ws.isoformat(),
                }
                act.start_date = _ist_midnight(ws)
            if to_ist_calendar_date(act.end_date) != we:
                change["end_date"] = {
                    "before": to_ist_calendar_date(act.end_date).isoformat(),
                    "after": we.isoformat(),
                }
                act.end_date = _ist_midnight(we)
            # Clamp allocation deployment dates into the (new) window — in place,
            # so quantities / rates / computed_cost snapshots and SLA mappings
            # are untouched.
            clamped = []
            for alloc in self.activities.list_planned_resources(act.id):
                deploy = alloc.planned_deployment_date
                if deploy is None:
                    continue
                snapped = min(max(deploy, ws), we)
                if snapped != deploy:
                    alloc.planned_deployment_date = snapped
                    clamped.append({
                        "designation": alloc.designation,
                        "before": deploy.isoformat(),
                        "after": snapped.isoformat(),
                    })
            if change or clamped:
                act.updated_by = caller_user_id
                self.audit.write(
                    project_id=milestone.project_id,
                    target_kind="activity", target_id=act.id,
                    action="realign", actor_user_id=caller_user_id,
                    changes={**change, "clamped_allocations": clamped},
                )
                realigned.append({
                    "activity_id": act.id,
                    "name": act.name,
                    "window": [ws.isoformat(), we.isoformat()],
                    "dates_changed": bool(change),
                    "allocations_clamped": len(clamped),
                })
        self.db.commit()
        return {"milestone_id": milestone_id, "realigned": realigned}

    def update(  # NOSONAR(S3776): sequential validation gates with order-sensitive side effects (validate -> mutate -> audit -> commit -> depends_on cycle-check) -- refactor deferred to a sprint with FE regression coverage
        self,
        milestone_id: str,
        payload: MilestoneUpdateRequest,
        *, caller_user_id: Optional[str],
        request=None,
    ):
        row = self.get_by_id(milestone_id)
        # 2026-06-03 — meeting milestones are auto-managed by the publish
        # flow. Direct mutation is rejected so the FE doesn't accidentally
        # rename them or fiddle with their dates.
        self._assert_not_meeting_milestone(row, action="updated")
        updates = payload.model_dump(exclude_unset=True)
        # Compute `touched` from the ORIGINAL payload before any pops so
        # the field walker can gate sub-resource codes (depends_on,
        # vendor_ids) whose values are processed separately below.
        touched = set(updates.keys())
        depends_on = updates.pop("depends_on", None)
        vendor_ids = updates.pop("vendor_ids", None)
        # Doc-finance: category + ccn_value have their own lifecycle rules.
        # Pop them out of the generic ``updates`` dict and handle them
        # before the generic field updates fire (so audit + cap checks
        # happen in the right order). The values are merged back into
        # ``updates`` once validated so the standard write path picks
        # them up.
        category_requested = updates.pop("category", None)
        ccn_value_requested = updates.pop("ccn_value", None)
        category_after, ccn_value_after = self._resolve_update_finance_fields(
            row=row,
            category_requested=category_requested,
            ccn_value_requested=ccn_value_requested,
        )
        if category_after is not None:
            updates["category"] = category_after
        if ccn_value_after is not None:
            updates["ccn_value"] = ccn_value_after
        if not updates and depends_on is None and vendor_ids is None:
            return row

        # Required-field parity with create: a PATCH may omit these (no
        # change) but may not clear them to empty. (Meeting milestones are
        # already blocked from update above.)
        assert_required_not_cleared(
            updates,
            {"name": "name", "start_date": "startDate", "end_date": "endDate"},
            entity="milestone",
        )

        # ----- catalog + transition validations on touched fields ------
        # Status validation lives at the schema level (2-value hardcoded
        # set: not_completed / completed) — service-level catalog check
        # is skipped here to match monolith.
        if "priority" in updates:
            self._validate_priority(updates["priority"])
        if "payment_type" in updates:
            self._validate_payment_type(updates["payment_type"])
        # Status-completion + parent-revert gates fire when status changes.
        if "status" in updates and updates["status"] is not None:
            new_status = updates["status"]
            if is_terminal_status(new_status) and not is_terminal_status(row.status):
                # Completing — validate every dep + every child activity is complete.
                self._assert_deps_completed(row.id)
                self._assert_all_child_activities_completed(row.id)
        # Vendor replacement: resolve + verify on-project.
        canonical_vendor_ids = None
        if vendor_ids is not None:
            canonical_vendor_ids = resolve_and_validate_vendor_ids(
                self.db, vendor_ids,
            )
            self._assert_vendors_on_project(row.project_id, canonical_vendor_ids)

        # Date-floor re-validation against the merged values. Apply the
        # same parent-floor + actual-date ordering rules the monolith
        # uses on PATCH.
        if (
            "start_date" in updates or "end_date" in updates
            or "actual_start_date" in updates or "actual_end_date" in updates
        ):
            project = self.projects.get_by_id(row.project_id)
            new_start = updates.get("start_date", row.start_date)
            new_end = updates.get("end_date", row.end_date)
            new_actual_start = updates.get(
                "actual_start_date", row.actual_start_date,
            )
            new_actual_end = updates.get(
                "actual_end_date", row.actual_end_date,
            )
            validate_entity_dates(
                entity_start=new_start,
                entity_end=new_end,
                actual_start=new_actual_start,
                actual_end=new_actual_end,
                parent_start_date=project.start_date if project else None,
                project_start_date=project.start_date if project else None,
                entity_label="milestone",
                parent_label="project",
            )
            # REVERSE Doc-31: this row's date move must not break any
            # downstream dependent's outlasting rule.
            self._assert_dep_dates_reverse(row, new_start, new_end)

        # Field-level RBAC: use the `touched` set computed before pops so
        # sub-resource codes (milestones:update:dependencies / vendors) gate.
        if request is not None and touched:
            from app.core.permissions import MILESTONE_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=MILESTONE_FIELD_CODES,
                touched_fields=touched,
                scope_key=("project", row.project_id),
            )

        if updates:
            before = {k: getattr(row, k) for k in updates}
            self.repo.update(row, updated_by=caller_user_id, **updates)
            self.audit.write(
                project_id=row.project_id,
                target_kind="milestone", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={
                    k: {"before": before[k], "after": updates[k]}
                    for k in updates
                },
            )
        if depends_on is not None:
            resolved_deps = self._resolve_depends_on(row.project_id, depends_on)
            self._guard_dependency_cycle(row.id, resolved_deps)
            if resolved_deps:
                self._assert_deps_exist(resolved_deps)
                self._assert_dep_dates_outlasting(row, resolved_deps)
            self.repo.replace_dependencies(row.id, resolved_deps)
            self.audit.write(
                project_id=row.project_id,
                target_kind="milestone", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={"depends_on": resolved_deps},
            )
        if canonical_vendor_ids is not None:
            self.repo.set_vendor_mapping(row.id, canonical_vendor_ids)
            self.audit.write(
                project_id=row.project_id,
                target_kind="milestone", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={"vendor_ids": canonical_vendor_ids},
            )
        # Cascade: if status transitioned to terminal, try to roll up
        # to the project.
        if (
            "status" in updates and updates["status"] is not None
            and is_terminal_status(updates["status"])
        ):
            self._cascade_to_parent(row, caller_user_id=caller_user_id)

        # Auto-tile quarters when a milestone becomes resource-based or its
        # window changes AND it has no activities yet (the helper's idempotent
        # guard). Existing SLA-mapped activities are realigned via the
        # dedicated endpoint, never regenerated here.
        if row.is_resource_based and (
            "is_resource_based" in updates
            or "start_date" in updates
            or "end_date" in updates
        ):
            self._autogenerate_quarter_activities(row, caller_user_id=caller_user_id)

        self.db.commit()
        return row

    def delete(self, milestone_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(milestone_id)
        # 2026-06-03 — the meeting milestone is auto-managed; refuse to
        # soft-delete it (would leave existing meeting activities
        # orphaned).
        self._assert_not_meeting_milestone(row, action="deleted")
        # Finance-page guard: a milestone bound to a live project-cost row
        # cannot be deleted — it would orphan the cost bundle + its
        # auto-managed payment term. Caller must remove it from finance first.
        from app.repositories.project_cost_item_repository import (
            ProjectCostItemRepository,
        )
        if ProjectCostItemRepository(self.db).is_milestone_bound(row.id):
            raise ConflictError(
                "This milestone is used on the project finance page. Remove it "
                "from the finance page (cost rows) first, then delete the milestone.",
                code="conflict",
                details={"milestone_id": row.id, "project_id": row.project_id},
            )
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, milestone_id: str, *, caller_user_id: Optional[str]):
        row = self.repo.get_by_id(milestone_id, include_deleted=True)
        if row is None:
            raise MilestoneNotFoundError("The milestone could not be found.")
        # Restoring a deleted meeting milestone is also auto-managed —
        # if a project needs one, the publish/JIT path will create it.
        self._assert_not_meeting_milestone(row, action="restored")
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    @staticmethod
    def _assert_not_meeting_milestone(row, *, action: str) -> None:
        """Refuse direct mutation of a meeting milestone. The publish flow
        and the project-detail JIT path own its lifecycle; user-driven
        PATCH / DELETE / restore would bypass that ownership."""
        if getattr(row, "is_meeting", False):
            raise ConflictError(
                f"Meeting milestones cannot be {action}. They are "
                f"managed automatically by the publish flow.",
                code="meeting_milestone_immutable",
                details={"milestone_id": row.id},
            )

    # ----------------------------------------------------- dependency guard

    # ----------------------------------------------- catalog + gates -----

    def _validate_status(self, status: Optional[str]) -> None:
        if status is None:
            return
        if is_known_milestone_status(self.db, status):
            return
        allowed = active_milestone_statuses(self.db)
        raise ValidationError(
            f"Milestone status must be one of: {', '.join(allowed)}."
        )

    def _validate_priority(self, priority: Optional[str]) -> None:
        if priority is None:
            return
        if is_known_priority(self.db, priority):
            return
        allowed = active_priorities(self.db)
        raise ValidationError(
            f"Priority must be one of: {', '.join(allowed)}."
        )

    def _validate_payment_type(self, payment_type: Optional[str]) -> None:
        if payment_type is None:
            return
        if is_known_payment_type(self.db, payment_type):
            return
        allowed = active_payment_types(self.db)
        raise ValidationError(
            f"Payment type must be one of: {', '.join(allowed)}."
        )

    def _assert_vendors_on_project(
        self, project_id: str, vendor_ids: List[str],
    ) -> None:
        """Each milestone vendor must already be attached to the parent
        project (monolith parity — see
        ``PMIS-OpenProject/app/api/v3/milestones/services/create.py``
        and the project-vendor join enforced for activities)."""
        if not vendor_ids:
            return
        from sqlalchemy import select
        from app.models.project_vendor import ProjectVendor
        rows = self.db.execute(
            select(ProjectVendor.vendor_id)
            .where(ProjectVendor.project_id == project_id)
            .where(ProjectVendor.vendor_id.in_(vendor_ids))
        ).all()
        attached = {r[0] for r in rows}
        missing = [v for v in vendor_ids if v not in attached]
        if missing:
            raise ValidationError(
                f"Vendor(s) not attached to this project: "
                f"{', '.join(missing)}. Add them to the project first."
            )

    def _assert_deps_exist(
        self, depends_on_ids: List[str],
    ) -> None:
        """Every dependency target must be a real, non-deleted milestone — in
        ANY project (cross-project dependencies are allowed). Meeting
        milestones still can't be targets (not part of deliverable scope), and
        unknown / wrong-type ids are rejected."""
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.milestone import Milestone
        # Meeting milestones can't participate in milestone dependencies
        # (they aren't part of the deliverable scope, so chaining onto them
        # would be nonsensical). Treat as "missing" so the caller gets a
        # clear error rather than silently accepting the link.
        rows = self.db.execute(
            select(Milestone.id)
            .where(Milestone.id.in_(depends_on_ids))
            .where(Milestone.deleted_at.is_(None))
            .where(Milestone.is_meeting.is_(False))
        ).all()
        found = {r[0] for r in rows}
        missing = [d for d in depends_on_ids if d not in found]
        if missing:
            raise ValidationError(
                f"Unknown milestone dependency target(s): {', '.join(missing)}"
            )

    def _assert_dep_dates_outlasting(
        self, source_row, depends_on_ids: List[str],
    ) -> None:
        """Doc-31 outlasting: source.start >= every target.start AND
        source.end > every target.end (strict). Errors match monolith."""
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.milestone import Milestone
        from app.utilities.dep_date_rules import (
            collect_forward_violations,
            raise_forward_if_violations,
        )
        rows = self.db.execute(
            select(Milestone.name, Milestone.start_date, Milestone.end_date)
            .where(Milestone.id.in_(depends_on_ids))
        ).all()
        targets = [(name, s, e) for name, s, e in rows]
        starts, ends = collect_forward_violations(
            source_start=source_row.start_date,
            source_end=source_row.end_date,
            targets=targets,
        )
        raise_forward_if_violations(
            starts, ends,
            source_label=f"'{source_row.name}'",
            source_start=source_row.start_date,
            source_end=source_row.end_date,
            kind_singular="milestone",
        )

    def _assert_dep_dates_reverse(
        self, target_row, new_start, new_end,
    ) -> None:
        """Doc-31 REVERSE: when this row's dates change, every milestone
        that depends ON it must still satisfy outlasting against the new
        target window."""
        from sqlalchemy import select
        from app.models.milestone import Milestone
        from app.models.milestone_dependency import MilestoneDependency
        from app.utilities.dep_date_rules import (
            collect_reverse_violations,
            raise_reverse_if_violations,
        )
        rows = self.db.execute(
            select(Milestone.name, Milestone.start_date, Milestone.end_date)
            .join(
                MilestoneDependency,
                MilestoneDependency.from_milestone_id == Milestone.id,
            )
            .where(MilestoneDependency.to_milestone_id == target_row.id)
            .where(Milestone.deleted_at.is_(None))
        ).all()
        if not rows:
            return
        sources = [(name, s, e) for name, s, e in rows]
        starts, ends = collect_reverse_violations(
            target_start=new_start,
            target_end=new_end,
            sources=sources,
        )
        raise_reverse_if_violations(
            starts, ends,
            target_label=f"Milestone '{target_row.name}'",
            target_start=new_start,
            target_end=new_end,
            kind_singular="milestone",
        )

    def _assert_deps_completed(self, milestone_id: str) -> None:
        """Dependency-completion gate (monolith parity, _gate_status_against_deps).
        Block flipping a milestone's status to ``completed`` while any of its
        dependency targets are still ``not_completed``. Mirrors monolith
        ``PMIS-OpenProject/app/api/v3/milestones/services/update.py``.
        """
        from sqlalchemy import select
        from app.models.milestone import Milestone
        dep_ids = self.repo.list_dependencies_for(milestone_id)
        if not dep_ids:
            return
        rows = self.db.execute(
            select(Milestone.name, Milestone.status)
            .where(Milestone.id.in_(dep_ids))
            .where(Milestone.deleted_at.is_(None))
        ).all()
        blockers = [name for name, status in rows if not is_terminal_status(status)]
        if not blockers:
            return
        names = ", ".join(f"'{n}'" for n in blockers[:3])
        more = f" (+{len(blockers) - 3} more)" if len(blockers) > 3 else ""
        raise ValidationError(
            f"Cannot mark this milestone as completed — the following "
            f"dependency target(s) are not yet completed: {names}{more}."
        )

    def _assert_all_child_activities_completed(
        self, milestone_id: str,
    ) -> None:
        """Children-completion gate (monolith parity): a milestone can
        only flip to completed when every live child activity is also
        completed. Error message matches monolith verbatim."""
        from sqlalchemy import select
        from app.models.activity import Activity
        rows = self.db.execute(
            select(Activity.name, Activity.status)
            .where(Activity.milestone_id == milestone_id)
            .where(Activity.deleted_at.is_(None))
        ).all()
        pending = [name for name, status in rows if not is_terminal_status(status)]
        if not pending:
            return
        names = ", ".join(pending[:5])
        more = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
        plural = "ies are" if len(pending) > 1 else "y is"
        raise ValidationError(
            f"Cannot mark this milestone as completed — the following "
            f"child activit{plural} not yet completed: {names}{more}."
        )

    # ------------------------------------------ display-code resolver -----

    def _resolve_depends_on(
        self, project_id: str, raw_ids: List[str],
    ) -> List[str]:
        """Resolve a mix of UUIDs and display codes (e.g. 'M1') to UUIDs.

        The FE normalizes milestone node.id to serverDisplayCode (M{n}) via
        normalizeProject, so depends_on arrives as display codes rather than
        UUIDs (Bug #6). Milestones use M{position} format.
        """
        if not raw_ids:
            return []
        from sqlalchemy import select
        from app.models.milestone import Milestone

        positions: List[int] = []
        uuid_ids: List[str] = []
        for dep_id in raw_ids:
            match = _MILESTONE_DISPLAY_CODE_RE.match(dep_id)
            if match:
                positions.append(int(match.group(1)))
            else:
                uuid_ids.append(dep_id)

        resolved = list(uuid_ids)
        if positions:
            # Meeting milestones don't get a M{n} display position
            # (filtered from the tree-service label index), so position-
            # based resolution must skip them too.
            rows = self.db.execute(
                select(Milestone.id)
                .where(Milestone.project_id == project_id)
                .where(Milestone.position.in_(positions))
                .where(Milestone.deleted_at.is_(None))
                .where(Milestone.is_meeting.is_(False))
            ).all()
            resolved.extend(r[0] for r in rows)
        return resolved

    # ----------------------------------------------------- dep cycle -----

    def _guard_dependency_cycle(
        self, milestone_id: str, depends_on_ids: List[str],
    ) -> None:
        """Reject self-deps + any transitive cycle that closes back on
        ``milestone_id``. Monolith parity — raises ``ValidationError``
        (422) with the message format ``"Adding milestone dependency on
        <uuid> would create a cycle."``.
        """
        if milestone_id in depends_on_ids:
            raise ValidationError(
                f"Adding milestone dependency on {milestone_id} would "
                f"create a cycle."
            )
        visited: set[str] = set()
        frontier = list(depends_on_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == milestone_id:
                offender = depends_on_ids[0]
                raise ValidationError(
                    f"Adding milestone dependency on {offender} would "
                    f"create a cycle."
                )
            frontier.extend(self.repo.list_dependencies_for(current))

    # ------------------------------------------ auto-complete cascade ----

    AUTO_COMPLETE_REASON = "Auto-completed: all milestones completed."

    def _attempt_auto_complete(
        self, row, *, caller_user_id: Optional[str],
        triggering_child_id: Optional[str],
    ) -> None:
        """Best-effort auto-complete of this milestone when invoked by a
        child activity's cascade. Silent no-op if already terminal, any
        live child activity is non-terminal, or own deps not satisfied.
        On success, propagates upward to the project.
        """
        from sqlalchemy import select
        from app.models.activity import Activity
        if is_terminal_status(row.status):
            return
        rows = list(self.db.execute(
            select(Activity.status)
            .where(Activity.milestone_id == row.id)
            .where(Activity.deleted_at.is_(None))
        ).all())
        if not rows or not all(is_terminal_status(s) for (s,) in rows):
            return
        try:
            self._assert_deps_completed(row.id)
        except ValidationError:
            return
        before = row.status
        self.repo.update(row, updated_by=caller_user_id, status="completed")
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="auto_complete", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "completed"},
                "by_child": triggering_child_id,
            },
        )
        self._cascade_to_parent(row, caller_user_id=caller_user_id)

    def _cascade_to_parent(self, row, *, caller_user_id: Optional[str]) -> None:
        """Walk one step up: milestone -> parent project. The project
        rollup uses status='closed' with a system-generated
        ``status_explanation`` (no separate 'completed' state exists in
        the project lifecycle catalog).
        """
        self._attempt_auto_complete_project(
            project_id=row.project_id,
            caller_user_id=caller_user_id,
            triggering_child_id=row.id,
        )

    def _attempt_auto_complete_project(
        self, *, project_id: str, caller_user_id: Optional[str],
        triggering_child_id: Optional[str],
    ) -> None:
        """Mark the project closed when all its live milestones are
        terminal. ``status_explanation`` is set to the auto-complete
        marker only when previously empty — manual close reasons are
        preserved.

        Lifecycle gate: auto-close only fires for projects in
        ``status='published'``. Projects in ``new`` / ``draft`` are
        still being configured (the user hasn't launched them yet),
        so even if every milestone is marked completed during setup
        the project must NOT be force-closed. Projects already in
        ``closed`` are terminal and skipped.
        """
        from app.models.milestone import Milestone
        from app.models.project import Project
        from sqlalchemy import select

        project = self.db.execute(
            select(Project).where(Project.id == project_id)
        ).scalar_one_or_none()
        if project is None:
            return
        if project.status != "published":
            return
        # Auto-close fires only when EVERY deliverable milestone is in a
        # terminal state. Meeting milestones are auto-created with
        # ``status="not_completed"`` and stay that way for the life of the
        # project — if we didn't filter them out here, no published project
        # could ever satisfy the all-terminal check and auto-close would
        # silently never fire. Filter ``is_meeting=False`` keeps the check
        # restricted to real deliverable milestones.
        rows = list(self.db.execute(
            select(Milestone.status)
            .where(Milestone.project_id == project_id)
            .where(Milestone.deleted_at.is_(None))
            .where(Milestone.is_meeting.is_(False))
        ).all())
        if not rows or not all(is_terminal_status(s) for (s,) in rows):
            return
        before = project.status
        update_kwargs = {"status": "closed", "updated_by": caller_user_id}
        if not (project.status_explanation or "").strip():
            update_kwargs["status_explanation"] = self.AUTO_COMPLETE_REASON
        self.projects.update(project, **update_kwargs)
        self.audit.write(
            project_id=project.id,
            target_kind="project", target_id=project.id,
            action="auto_complete", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "closed"},
                "by_child": triggering_child_id,
            },
            note=self.AUTO_COMPLETE_REASON,
        )

    # --------------------------------------- reverse cascade (Q9) ---------

    def _auto_revert(
        self, row, *, caller_user_id: Optional[str],
        triggering_child_id: Optional[str],
    ) -> None:
        """Flip a terminal milestone back to not_completed, audit.
        Stops here — the project boundary does NOT participate in the
        reverse cascade. (Milestone create on a closed project is
        blocked by the reopen gate; on published / draft / new the
        project is not 'completed' and needs no revert.)
        """
        if not is_terminal_status(row.status):
            return
        before = row.status
        self.repo.update(row, updated_by=caller_user_id, status="not_completed")
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="auto_revert", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "not_completed"},
                "by_child": triggering_child_id,
            },
        )

    # ----------------------------------------- Doc-finance ---------------

    def _resolve_create_category(
        self, *, project,
        requested_category: Optional[str],
        requested_ccn_value: Optional[Decimal],
    ) -> tuple[str, Decimal]:
        """Resolve (category, ccn_value) for a milestone CREATE based on
        project state.

        Pre-publish (status != 'published'): always 'original' / 0; any
        client-sent category/ccn_value is silently ignored (preserves
        existing FE behavior, additive contract).

        Post-publish (status == 'published'):
          * category=None or missing → default to 'asg' (no money).
          * category='original' → rejected 422 (not allowed post-publish).
          * category='asg' → ccn_value forced to 0.
          * category='ccn' → ccn_value required > 0; cap check (hard 409
            on overflow when TPV > 0; bypassed when TPV = 0).
        """
        is_published = (project.status or "").lower() == "published"
        if not is_published:
            # Pre-publish: ignore both. Server enforces the baseline.
            return _CATEGORY_ORIGINAL, Decimal("0")

        category = (requested_category or _CATEGORY_ASG).lower()
        if category == _CATEGORY_ORIGINAL:
            raise ValidationError(
                "Category 'original' is only valid for items created before "
                "the project is published. Use 'asg' or 'ccn' for "
                "post-publish creates.",
                details={"project_status": project.status},
            )
        if category not in _VALID_CATEGORIES:
            raise ValidationError(
                f"Category must be one of: {', '.join(_VALID_CATEGORIES)}.",
            )

        if category == _CATEGORY_ASG:
            return _CATEGORY_ASG, Decimal("0")

        # category == _CATEGORY_CCN
        ccn_value = requested_ccn_value if requested_ccn_value is not None else Decimal("0")
        if Decimal(ccn_value) <= 0:
            raise ValidationError(
                "ccn_value must be greater than 0 when category is 'ccn'.",
            )
        # Cumulative cap check (Q4.1 default — hard reject 409 on overflow).
        existing_used = self.finance.sum_ccn_used(project.id)
        if ccn_calc.would_exceed_cap(
            tpv_excl_tax=project.total_project_value_excl_tax,
            ccn_cap_percent=project.ccn_cap_percent,
            existing_ccn_used=existing_used,
            new_ccn_value=ccn_value,
        ):
            details = ccn_calc.cap_exceed_details(
                tpv_excl_tax=project.total_project_value_excl_tax,
                ccn_cap_percent=project.ccn_cap_percent,
                existing_ccn_used=existing_used,
                new_ccn_value=ccn_value,
            )
            raise ConflictError(
                "CCN value exceeds the project CCN cap. Cumulative CCN "
                "usage would surpass the contractual extension limit.",
                code="ccn_cap_exceeded",
                details=details,
            )
        return _CATEGORY_CCN, Decimal(ccn_value)

    def _resolve_update_finance_fields(
        self, *, row,
        category_requested: Optional[str],
        ccn_value_requested: Optional[Decimal],
    ) -> tuple[Optional[str], Optional[Decimal]]:
        """Resolve the (category, ccn_value) deltas for a milestone PATCH.

        Returns ``(category_after_or_None, ccn_value_after_or_None)``.
        ``None`` means "don't write this column". Rules:

          * ``category`` is locked once set: any attempt to change it →
            409. (Sending the same value is a no-op.)
          * ``ccn_value`` is only editable when the row's existing
            category is 'ccn'. Editing on an ASG or original row → 422.
          * Cumulative cap check applies (with displacement of the row's
            current value) when TPV > 0; bypassed when TPV = 0.
        """
        category_after: Optional[str] = None
        ccn_value_after: Optional[Decimal] = None

        if category_requested is not None:
            requested = category_requested.lower()
            if requested != (row.category or _CATEGORY_ORIGINAL):
                raise ConflictError(
                    "Category is locked once the item is saved and cannot "
                    "be changed.",
                    code="conflict",
                    details={
                        "current_category": row.category,
                        "requested_category": requested,
                    },
                )
            # Same value — no-op, don't add to updates.

        if ccn_value_requested is not None:
            if (row.category or _CATEGORY_ORIGINAL) != _CATEGORY_CCN:
                raise ValidationError(
                    "ccn_value is only editable for items with "
                    "category='ccn'.",
                    details={"current_category": row.category},
                )
            new_value = Decimal(ccn_value_requested)
            if new_value <= 0:
                raise ValidationError(
                    "ccn_value must be greater than 0 when category is 'ccn'.",
                )
            project = self.projects.get_by_id(row.project_id)
            if project is None:
                raise ProjectNotFoundError(
                    "The parent project could not be found."
                )
            # Displacement — subtract the row's prior contribution before
            # the cumulative check.
            prior = Decimal(row.ccn_value or 0)
            existing_used = self.finance.sum_ccn_used(project.id) - prior
            if existing_used < 0:
                existing_used = Decimal("0")
            if ccn_calc.would_exceed_cap(
                tpv_excl_tax=project.total_project_value_excl_tax,
                ccn_cap_percent=project.ccn_cap_percent,
                existing_ccn_used=existing_used,
                new_ccn_value=new_value,
            ):
                details = ccn_calc.cap_exceed_details(
                    tpv_excl_tax=project.total_project_value_excl_tax,
                    ccn_cap_percent=project.ccn_cap_percent,
                    existing_ccn_used=existing_used,
                    new_ccn_value=new_value,
                )
                raise ConflictError(
                    "CCN value update would push cumulative CCN over the "
                    "project cap.",
                    code="ccn_cap_exceeded",
                    details=details,
                )
            ccn_value_after = new_value
        return category_after, ccn_value_after
