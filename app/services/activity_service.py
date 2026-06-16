"""ActivityService — CRUD + dependency cycle guard + inline-comment / files."""
from __future__ import annotations

import base64
import binascii
import re
from io import BytesIO
from typing import List, Optional

# FE normalizes activity node.id to the WBS display code (e.g. "A1.2") after
# normalizeProject runs, so depends_on arrives as display codes rather than
# UUIDs. Bug #12: resolve them to UUIDs via milestone+activity position lookup.
_ACTIVITY_DISPLAY_CODE_RE = re.compile(r"^A(\d+)\.(\d+)$", re.IGNORECASE)

from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from decimal import Decimal

from app.core.errors import (
    ActivityNotFoundError,
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
from app.schemas.activity import (
    ActivityAttachmentInput,
    ActivityCreateRequest,
    ActivityUpdateRequest,
)
from app.utilities import ccn_calc
from app.utilities.catalogs import (
    active_activity_statuses,
    active_owner_divisions,
    active_priorities,
    is_known_activity_status,
    is_known_owner_division,
    is_known_priority,
    is_terminal_status,
)
from app.utilities.date_rules import validate_entity_dates
from app.utilities.multipart_form import (
    pre_validate_files,
    upload_files_via_client,
)
from app.utilities.project_lock import assert_milestone_activity_writable
from app.utilities.required_fields import assert_required_not_cleared
from app.utilities.vendor_resolver import assert_vendor_in_project


# Doc-finance: category choices (mirrors milestone_service constants).
_CATEGORY_ORIGINAL = "original"
_CATEGORY_ASG = "asg"
_CATEGORY_CCN = "ccn"
_VALID_CATEGORIES = (_CATEGORY_ORIGINAL, _CATEGORY_ASG, _CATEGORY_CCN)


class ActivityService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ActivityRepository(db)
        self.milestones = MilestoneRepository(db)
        self.projects = ProjectRepository(db)
        self.comments = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)
        self.finance = FinanceRepository(db)

    def get_by_id(self, activity_id: str):
        row = self.repo.get_by_id(activity_id)
        if row is None:
            raise ActivityNotFoundError("The activity could not be found.")
        return row

    def list_for_milestone(
        self, milestone_id: str, *, offset=1, page_size=50, include_deleted=False,
    ):
        return self.repo.list_for_milestone(
            milestone_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted,
        )

    def create(
        self,
        milestone_id: str,
        payload: ActivityCreateRequest,
        *,
        caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        milestone = self.milestones.get_by_id(milestone_id)
        if milestone is None:
            raise MilestoneNotFoundError("The milestone could not be found.")
        project = self.projects.get_by_id(milestone.project_id)
        assert_milestone_activity_writable(project)
        # Closed projects are frozen: no new activities until reopened
        # (mirrors the milestone-create gate).
        if (getattr(project, "status", None) or "").lower() == "closed":
            raise ValidationError(
                "Project is closed. Reopen project first to add activities.",
                details={"project_id": milestone.project_id, "project_status": "closed"},
            )
        # Required-field parity with the create UI. A non-meeting activity
        # must carry owner division, organization (vendor), priority and at
        # least one concerned division — the same fields the UI marks
        # mandatory. Meeting/governance activities are created without these
        # business fields, so they are exempt.
        if not getattr(milestone, "is_meeting", False):
            self._assert_activity_create_required(payload)
        # Status validation is schema-level (2-value hardcoded set per
        # monolith parity); priority + ownerDivision are service-level
        # catalog checks; concerned_divisions accepted silently (no
        # catalog check on the wire — monolith parity).
        self._validate_priority(payload.priority)
        self._validate_owner_division(payload.owner_division)
        self._validate_concerned_divisions(payload.concerned_divisions)
        # Vendor (when supplied) must be attached to the parent project.
        if payload.vendor_id:
            assert_vendor_in_project(
                self.db, project_id=milestone.project_id,
                vendor_id=payload.vendor_id,
            )
        # Date rules — parent floor is the owning milestone (monolith parity).
        # Per bug #206: activities are exempt from the project-start floor on
        # actual_start_date — users may "start" an activity before the project
        # start date. The parent-milestone floor on planned start_date stays.
        validate_entity_dates(
            entity_start=payload.start_date,
            entity_end=payload.end_date,
            actual_start=payload.actual_start_date,
            actual_end=payload.actual_end_date,
            parent_start_date=milestone.start_date,
            project_start_date=None,
            entity_label="activity",
            parent_label="milestone",
        )
        # Meeting-activity inline attachments (base64) — see schema
        # ``ActivityAttachmentInput``. Decoded, validated, and written to
        # storage HERE (before the row is inserted) so a rejected file
        # never leaves an orphan activity — mirroring the multipart route's
        # upload-before-create ordering. Permitted only for meeting
        # milestones; the envelopes are persisted on the inline comment row
        # built below.
        meeting_attachment_envelopes = self._prepare_meeting_attachments(
            milestone, payload.attachments,
        )
        position = (
            payload.position
            if payload.position is not None and payload.position > 0
            else self.repo.next_position_for_milestone(milestone_id)
        )
        # Doc-finance: resolve category + ccn_value based on project state.
        category, ccn_value = self._resolve_create_category(
            project=project,
            requested_category=payload.category,
            requested_ccn_value=payload.ccn_value,
        )
        row = self.repo.create(
            project_id=milestone.project_id,
            milestone_id=milestone_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            actual_start_date=payload.actual_start_date,
            actual_end_date=payload.actual_end_date,
            status=payload.status,
            activity_started=bool(payload.activity_started),
            priority=payload.priority,
            owner_division=payload.owner_division,
            concerned_divisions=payload.concerned_divisions,
            vendor_id=payload.vendor_id,
            position=position,
            category=category,
            ccn_value=ccn_value,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if payload.depends_on:
            resolved_deps = self._resolve_depends_on(row.project_id, payload.depends_on)
            self._guard_dependency_cycle(row.id, resolved_deps)
            self._assert_deps_in_same_project(row.project_id, resolved_deps)
            self._assert_dep_dates_outlasting(row, resolved_deps)
            self.repo.replace_dependencies(row.id, resolved_deps)

        # Inline comment / attachments — written under the new activity.
        # Captured on ``_inline_comment`` so the controller can echo the
        # comment back on the multipart-create response (monolith parity).
        body_clean = (body or "").strip() or None
        atts = list(attachments or [])
        if meeting_attachment_envelopes:
            atts.extend(meeting_attachment_envelopes)
        row._inline_comment = None
        if body_clean or atts:
            row._inline_comment = self.comments.create(
                target_kind="activity",
                target_id=row.id,
                author_user_id=caller_user_id,
                body=body_clean,
                attachments=atts or None,
            )

        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "milestone_id": row.milestone_id},
        )
        # Doc-finance: dedicated audit entry for post-publish ASG / CCN
        # activity creates so the lineage is searchable separately.
        if row.category == _CATEGORY_CCN:
            self.audit.write(
                project_id=row.project_id,
                target_kind="activity", target_id=row.id,
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
                project_id=row.project_id,
                target_kind="activity", target_id=row.id,
                action="create_asg", actor_user_id=caller_user_id,
                changes={"category": _CATEGORY_ASG},
            )
        # Reverse cascade: new (not_completed) activity invalidates a
        # terminal milestone.
        self._cascade_revert_from_new_child(row, caller_user_id=caller_user_id)
        self.db.commit()
        return row

    def _assert_activity_create_required(self, payload) -> None:
        """Create-time mandatory-field gate mirroring the activity UI.

        Owner division, organization (vendor), priority and at least one
        concerned division are required to create a non-meeting activity.
        Raises a single 422 listing every missing field by wire name. The
        update/PATCH path is intentionally NOT gated here — partial updates
        stay partial. Meeting/governance activities are exempt and never
        reach this method (see ``create``).
        """
        missing: list[str] = []
        if not (payload.owner_division and str(payload.owner_division).strip()):
            missing.append("ownerDivision")
        if not (payload.vendor_id and str(payload.vendor_id).strip()):
            missing.append("vendorId")
        if not (payload.priority and str(payload.priority).strip()):
            missing.append("priority")
        if not payload.concerned_divisions:
            missing.append("concernedDivision")
        if missing:
            raise ValidationError(
                "Missing required field(s) for activity creation: "
                f"{', '.join(missing)}.",
                details={"missing": missing},
            )

    def _prepare_meeting_attachments(
        self, milestone, attachments: Optional[List[ActivityAttachmentInput]],
    ) -> List[dict]:
        """Decode + validate + store inline (base64) meeting attachments.

        Returns the list of attachment envelopes (``{url, filename,
        mimeType, sizeBytes, uploadedAt}``) ready to persist on the new
        activity's comment row, or an empty list when there are none.

        Only permitted when ``milestone.is_meeting`` is True — the meeting
        (governance/mom) service is the sole caller that sends inline
        attachments, and they belong exclusively to meeting-type
        activities. Validation (size / extension / magic-byte) and storage
        reuse the exact same helpers + ``ATTACHMENTS_ALLOWED_EXTENSIONS``
        allow-list as every other attachment surface, so the behaviour and
        envelope shape are identical to the multipart path.

        Raises ``ValidationError`` (HTTP 422) when attachments are supplied
        for a non-meeting milestone, or when any ``content`` is not valid
        base64 / decodes to empty. Size / extension / magic-byte failures
        surface as their usual attachment errors.
        """
        if not attachments:
            return []
        if not getattr(milestone, "is_meeting", False):
            raise ValidationError(
                "Attachments can only be added on create for meeting "
                "activities.",
                details={"milestone_id": milestone.id},
            )
        uploads: List[UploadFile] = []
        for att in attachments:
            try:
                raw = base64.b64decode(att.content or "", validate=False)
            except (binascii.Error, ValueError):
                raise ValidationError(
                    f"Attachment {att.filename!r} has invalid base64 content.",
                    details={"filename": att.filename},
                )
            if not raw:
                raise ValidationError(
                    f"Attachment {att.filename!r} is empty.",
                    details={"filename": att.filename},
                )
            uploads.append(
                UploadFile(
                    file=BytesIO(raw),
                    filename=att.filename,
                    headers=Headers(
                        {
                            "content-type": (
                                att.content_type or "application/octet-stream"
                            )
                        }
                    ),
                )
            )
        pre_validate_files(uploads)
        return upload_files_via_client(uploads)

    def update(  # NOSONAR(S3776): sequential validation gates with order-sensitive side effects (validate -> mutate -> audit -> commit -> depends_on cycle-check) -- refactor deferred to a sprint with FE regression coverage
        self, activity_id: str, payload: ActivityUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ):
        row = self.get_by_id(activity_id)
        updates = payload.model_dump(exclude_unset=True)
        # Compute `touched` from the ORIGINAL payload before any pops so
        # the field walker can gate sub-resource codes (e.g. depends_on)
        # whose values are processed separately below.
        touched = set(updates.keys())
        depends_on = updates.pop("depends_on", None)
        # Doc-finance: handle category + ccn_value lifecycle separately.
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

        # Required-field parity with create: a PATCH may omit these (no
        # change) but may not clear them to empty. The business fields
        # (ownerDivision/vendorId/priority/concernedDivision) are required
        # only for non-meeting activities — same exemption as create.
        required = {
            "name": "name", "start_date": "startDate", "end_date": "endDate",
        }
        _business = {
            "owner_division": "ownerDivision", "vendor_id": "vendorId",
            "priority": "priority", "concerned_divisions": "concernedDivision",
        }
        if any(f in updates for f in _business):
            _milestone = self.milestones.get_by_id(row.milestone_id)
            if not getattr(_milestone, "is_meeting", False):
                required.update(_business)
        assert_required_not_cleared(updates, required, entity="activity")

        # ----- catalog + transition validations on touched fields ------
        # Status is schema-level — no service check.
        if "priority" in updates:
            self._validate_priority(updates["priority"])
        if "owner_division" in updates:
            self._validate_owner_division(updates["owner_division"])
        # concerned_divisions accepted silently (no catalog check).
        if "vendor_id" in updates and updates["vendor_id"]:
            assert_vendor_in_project(
                self.db, project_id=row.project_id,
                vendor_id=updates["vendor_id"],
            )
        # Status-completion gate (forward) + parent-revert gate.
        if "status" in updates and updates["status"] is not None:
            new_status = updates["status"]
            if is_terminal_status(new_status) and not is_terminal_status(row.status):
                self._assert_deps_completed(row.id)
                self._assert_all_child_tasks_completed(row.id)
            if (
                not is_terminal_status(new_status)
                and is_terminal_status(row.status)
            ):
                self._assert_parent_milestone_not_completed(row.milestone_id)

        # Date-floor re-validation against the merged values.
        if (
            "start_date" in updates or "end_date" in updates
            or "actual_start_date" in updates or "actual_end_date" in updates
        ):
            milestone = self.milestones.get_by_id(row.milestone_id)
            new_start = updates.get("start_date", row.start_date)
            new_end = updates.get("end_date", row.end_date)
            new_actual_start = updates.get("actual_start_date", row.actual_start_date)
            new_actual_end = updates.get("actual_end_date", row.actual_end_date)
            # Bug #206: activities are exempt from the project-start floor on
            # actual_start_date (see create-path comment above).
            validate_entity_dates(
                entity_start=new_start,
                entity_end=new_end,
                actual_start=new_actual_start,
                actual_end=new_actual_end,
                parent_start_date=milestone.start_date if milestone else None,
                project_start_date=None,
                entity_label="activity",
                parent_label="milestone",
            )
            self._assert_dep_dates_reverse(row, new_start, new_end)

        if request is not None and touched:
            from app.core.permissions import ACTIVITY_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=ACTIVITY_FIELD_CODES,
                touched_fields=touched,
                scope_key=("project", row.project_id),
            )

        if updates:
            before = {k: getattr(row, k) for k in updates}
            self.repo.update(row, updated_by=caller_user_id, **updates)
            self.audit.write(
                project_id=row.project_id,
                target_kind="activity", target_id=row.id,
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
                self._assert_deps_in_same_project(row.project_id, resolved_deps)
                self._assert_dep_dates_outlasting(row, resolved_deps)
            self.repo.replace_dependencies(row.id, resolved_deps)
            self.audit.write(
                project_id=row.project_id,
                target_kind="activity", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={"depends_on": resolved_deps},
            )
        # Cascade: if status transitioned to terminal, try to roll up.
        if (
            "status" in updates and updates["status"] is not None
            and is_terminal_status(updates["status"])
        ):
            self._cascade_to_parent(row, caller_user_id=caller_user_id)
        self.db.commit()
        return row

    def delete(self, activity_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(activity_id)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, activity_id: str, *, caller_user_id: Optional[str]):
        row = self.repo.get_by_id(activity_id, include_deleted=True)
        if row is None:
            raise ActivityNotFoundError("The activity could not be found.")
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    # ----------------------------------------------- catalog + gates -----

    def _validate_status(self, status: Optional[str]) -> None:
        if status is None:
            return
        if is_known_activity_status(self.db, status):
            return
        allowed = active_activity_statuses(self.db)
        raise ValidationError(
            f"Activity status must be one of: {', '.join(allowed)}."
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

    def _validate_owner_division(self, code: Optional[str]) -> None:
        # Monolith parity: error message format includes the master path.
        if code is None or not str(code).strip():
            return
        if is_known_owner_division(self.db, code):
            return
        raise ValidationError(
            f"ownerDivision '{code}' is not an active division. Pick one "
            f"from GET /api/v3/master/divisions."
        )

    def _validate_concerned_divisions(self, codes: Optional[List[str]]) -> None:
        # Monolith parity: concerned_divisions is NOT validated against
        # the divisions catalog on the wire. Any non-empty list of strings
        # is accepted as-is (the schema's ``min_length=1`` is the only
        # gate). Unknown codes pass through and get persisted.
        return

    def _assert_deps_in_same_project(
        self, project_id: str, depends_on_ids: List[str],
    ) -> None:
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.activity import Activity
        rows = self.db.execute(
            select(Activity.id)
            .where(Activity.id.in_(depends_on_ids))
            .where(Activity.project_id == project_id)
            .where(Activity.deleted_at.is_(None))
        ).all()
        found = {r[0] for r in rows}
        missing = [d for d in depends_on_ids if d not in found]
        if missing:
            raise ValidationError(
                f"Unknown or out-of-project activity dependency "
                f"target(s): {', '.join(missing)}"
            )

    def _assert_dep_dates_outlasting(
        self, source_row, depends_on_ids: List[str],
    ) -> None:
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.activity import Activity
        from app.utilities.dep_date_rules import (
            collect_forward_violations,
            raise_forward_if_violations,
        )
        rows = self.db.execute(
            select(Activity.name, Activity.start_date, Activity.end_date)
            .where(Activity.id.in_(depends_on_ids))
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
            kind_singular="activity",
        )

    def _assert_dep_dates_reverse(
        self, target_row, new_start, new_end,
    ) -> None:
        from sqlalchemy import select
        from app.models.activity import Activity
        from app.models.activity_dependency import ActivityDependency
        from app.utilities.dep_date_rules import (
            collect_reverse_violations,
            raise_reverse_if_violations,
        )
        rows = self.db.execute(
            select(Activity.name, Activity.start_date, Activity.end_date)
            .join(
                ActivityDependency,
                ActivityDependency.from_activity_id == Activity.id,
            )
            .where(ActivityDependency.to_activity_id == target_row.id)
            .where(Activity.deleted_at.is_(None))
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
            target_label=f"Activity '{target_row.name}'",
            target_start=new_start,
            target_end=new_end,
            kind_singular="activity",
        )

    def dependency_completion_status(self, activity_id: str) -> dict:
        """Read-only check of whether every dependency target of
        ``activity_id`` is in a terminal status.

        Returns ``{"eligible": bool, "blockers": [{"id", "name",
        "status"}]}`` where ``blockers`` lists the dependency targets that
        are NOT yet terminal. ``eligible`` is True when there are no such
        blockers — including the no-dependencies case. Does not raise and
        does not validate that ``activity_id`` itself exists (callers that
        need a 404 should load the row first).

        Shared by the completion-eligibility endpoint and the status-flip
        gate (``_assert_deps_completed``) so both apply identical logic.
        """
        from sqlalchemy import select
        from app.models.activity import Activity
        dep_ids = self.repo.list_dependencies_for(activity_id)
        if not dep_ids:
            return {"eligible": True, "blockers": []}
        rows = self.db.execute(
            select(Activity.id, Activity.name, Activity.status)
            .where(Activity.id.in_(dep_ids))
            .where(Activity.deleted_at.is_(None))
        ).all()
        blockers = [
            {"id": aid, "name": name, "status": status}
            for aid, name, status in rows
            if not is_terminal_status(status)
        ]
        return {"eligible": not blockers, "blockers": blockers}

    def completion_eligibility(self, activity_id: str) -> dict:
        """Read-only completion-eligibility for the public endpoint.

        Validates the activity exists (raising NotFound -> 404 otherwise),
        then returns ``{"activity_id", "eligible", "blocking_dependencies"}``
        computed from ``dependency_completion_status``. Pure read — mutates
        nothing.
        """
        self.get_by_id(activity_id)  # 404 when missing / soft-deleted
        status = self.dependency_completion_status(activity_id)
        return {
            "activity_id": activity_id,
            "eligible": status["eligible"],
            "blocking_dependencies": status["blockers"],
        }

    def _assert_deps_completed(self, activity_id: str) -> None:
        """Dependency-completion gate (monolith parity, _gate_status_against_deps).
        Block flipping an activity's status to ``completed`` while any of its
        dependency targets are still ``not_completed``. Mirrors monolith
        ``PMIS-OpenProject/app/api/v3/activities/services/update.py:88-118``.
        """
        result = self.dependency_completion_status(activity_id)
        if result["eligible"]:
            return
        blockers = [b["name"] for b in result["blockers"]]
        names = ", ".join(f"'{n}'" for n in blockers[:3])
        more = f" (+{len(blockers) - 3} more)" if len(blockers) > 3 else ""
        raise ValidationError(
            f"Cannot mark this activity as completed — the following "
            f"dependency target(s) are not yet completed: {names}{more}."
        )

    def _assert_all_child_tasks_completed(self, activity_id: str) -> None:
        """Children-completion gate. Mirrors milestone parity."""
        from sqlalchemy import select
        from app.models.task import Task
        rows = self.db.execute(
            select(Task.name, Task.status)
            .where(Task.activity_id == activity_id)
            .where(Task.deleted_at.is_(None))
        ).all()
        pending = [name for name, status in rows if not is_terminal_status(status)]
        if not pending:
            return
        names = ", ".join(pending[:5])
        more = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
        plural = "s are" if len(pending) > 1 else " is"
        raise ValidationError(
            f"Cannot mark this activity as completed — the following "
            f"child task{plural} not yet completed: {names}{more}."
        )

    def _assert_parent_milestone_not_completed(self, milestone_id: str) -> None:
        """Parent-revert gate (monolith parity): can't revert an activity
        to ``not_completed`` while its parent milestone is still completed."""
        m = self.milestones.get_by_id(milestone_id)
        if m is None or not is_terminal_status(m.status):
            return
        raise ValidationError(
            f"Cannot revert this activity to not_completed — its parent "
            f"milestone '{m.name}' is still completed. Revert the parent "
            f"milestone first."
        )

    # ------------------------------------------ display-code resolver -----

    def _resolve_depends_on(
        self, project_id: str, raw_ids: List[str],
    ) -> List[str]:
        """Resolve display codes (e.g. 'A1.2') mixed with UUIDs to UUIDs.

        The FE normalizes activity node.id to serverDisplayCode (A{ms}.{act})
        via normalizeProject, so depends_on arrives as display codes (Bug #12).
        Activities use A{milestone_position}.{activity_position} format.
        """
        if not raw_ids:
            return []
        from sqlalchemy import select
        from app.models.activity import Activity
        from app.models.milestone import Milestone

        lookups: List[tuple] = []
        uuid_ids: List[str] = []
        for dep_id in raw_ids:
            match = _ACTIVITY_DISPLAY_CODE_RE.match(dep_id)
            if match:
                lookups.append((int(match.group(1)), int(match.group(2))))
            else:
                uuid_ids.append(dep_id)

        resolved = list(uuid_ids)
        for ms_pos, act_pos in lookups:
            # Skip meeting milestones — they don't get an M{n} display code
            # in the tree, so display-code refs must never resolve to a
            # meeting activity. A direct UUID for a meeting activity still
            # resolves above via ``uuid_ids``.
            row = self.db.execute(
                select(Activity.id)
                .join(Milestone, Milestone.id == Activity.milestone_id)
                .where(Milestone.project_id == project_id)
                .where(Milestone.position == ms_pos)
                .where(Milestone.deleted_at.is_(None))
                .where(Milestone.is_meeting.is_(False))
                .where(Activity.position == act_pos)
                .where(Activity.deleted_at.is_(None))
            ).scalar_one_or_none()
            if row:
                resolved.append(row)
        return resolved

    # ----------------------------------------------------- dep cycle -----

    def _guard_dependency_cycle(
        self, activity_id: str, depends_on_ids: List[str],
    ) -> None:
        """Monolith parity — emits ``ValidationError`` (422) with the
        message format ``"Adding dependency on '<uuid>' would create a
        cycle."`` (generic 'dependency', UUID quoted)."""
        if activity_id in depends_on_ids:
            raise ValidationError(
                f"Adding dependency on '{activity_id}' would create a cycle."
            )
        visited: set[str] = set()
        frontier = list(depends_on_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == activity_id:
                offender = depends_on_ids[0]
                raise ValidationError(
                    f"Adding dependency on '{offender}' would create a cycle."
                )
            frontier.extend(self.repo.list_dependencies_for(current))

    # ------------------------------------------ auto-complete cascade ----

    def _attempt_auto_complete(
        self, row, *, caller_user_id: Optional[str],
        triggering_child_id: Optional[str],
    ) -> None:
        """Best-effort auto-complete of this activity when invoked by a
        child task's cascade. Silent no-op if already terminal, any live
        child task is non-terminal, or own deps not satisfied. On
        success, propagates upward to the milestone.
        """
        from sqlalchemy import select
        from app.models.task import Task
        if is_terminal_status(row.status):
            return
        # All live tasks under this activity must be terminal.
        rows = list(self.db.execute(
            select(Task.status)
            .where(Task.activity_id == row.id)
            .where(Task.deleted_at.is_(None))
        ).all())
        if not rows or not all(is_terminal_status(s) for (s,) in rows):
            return
        try:
            self._assert_deps_completed(row.id)
        except ValidationError:
            return
        before = row.status
        self.repo.update(row, status="completed", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="auto_complete", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "completed"},
                "by_child": triggering_child_id,
            },
        )
        self._cascade_to_parent(row, caller_user_id=caller_user_id)

    def _cascade_to_parent(self, row, *, caller_user_id: Optional[str]) -> None:
        """Walk one step up: activity -> parent milestone. Defers to
        MilestoneService for the actual auto-complete attempt.
        """
        from app.services.milestone_service import MilestoneService
        ms_service = MilestoneService(self.db)
        ms = ms_service.repo.get_by_id(row.milestone_id)
        if ms is not None:
            ms_service._attempt_auto_complete(
                ms, caller_user_id=caller_user_id,
                triggering_child_id=row.id,
            )

    def complete_from_workflow(
        self, row, *, caller_user_id: Optional[str],
    ) -> bool:
        """Mark this activity completed because its *approval workflow*
        reached the terminal (owner-approved) state, then cascade the
        completion up to the milestone (and project) via the canonical
        roll-up.

        Distinct from ``_attempt_auto_complete``: that path is driven by a
        child task finishing and therefore gates on "every live task is
        terminal" (and no-ops when the activity has no tasks). Workflow
        completion is driven by the owner's approval instead — the
        workflow's own SUBMIT pre-check (``approval_inbox_service.
        _assert_activity_ready_for_submit``) already enforced that tasks
        were done, and an activity with zero tasks must still complete. So
        this marks the activity completed regardless of task presence, then
        reuses ``_cascade_to_parent`` so the milestone auto-completes when
        all its live activities are now terminal.

        Idempotent and best-effort. Returns True when it flipped the status,
        False when the activity was already terminal / deleted / missing.
        """
        if row is None or getattr(row, "deleted_at", None) is not None:
            return False
        if is_terminal_status(row.status):
            return False
        before = row.status
        self.repo.update(row, status="completed", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="auto_complete", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "completed"},
                # Distinguishes a workflow-driven completion from a
                # child-task-driven one (which records ``by_child``).
                "by_workflow": True,
            },
        )
        self._cascade_to_parent(row, caller_user_id=caller_user_id)
        return True

    # --------------------------------------- reverse cascade (Q9) ---------

    def _cascade_revert_from_new_child(
        self, child_row, *, caller_user_id: Optional[str],
    ) -> None:
        """A new not_completed activity invalidates a terminal parent
        milestone. Stops at milestone — project-level revert is not
        performed (closed projects block milestone create via the
        reopen gate; if project is published, milestone revert leaves
        it published).
        """
        from app.services.milestone_service import MilestoneService
        ms_service = MilestoneService(self.db)
        ms = ms_service.repo.get_by_id(child_row.milestone_id)
        if ms is not None and is_terminal_status(ms.status):
            ms_service._auto_revert(
                ms, caller_user_id=caller_user_id,
                triggering_child_id=child_row.id,
            )

    def _auto_revert(
        self, row, *, caller_user_id: Optional[str],
        triggering_child_id: Optional[str],
    ) -> None:
        """Flip a terminal activity back to not_completed, audit, recurse
        up via the milestone."""
        if not is_terminal_status(row.status):
            return
        before = row.status
        self.repo.update(row, status="not_completed", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="auto_revert", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "not_completed"},
                "by_child": triggering_child_id,
            },
        )
        self._cascade_revert_from_new_child(row, caller_user_id=caller_user_id)

    # ----------------------------------------- Doc-finance ---------------

    def _resolve_create_category(
        self, *, project,
        requested_category: Optional[str],
        requested_ccn_value: Optional[Decimal],
    ) -> tuple[str, Decimal]:
        """Same lifecycle as MilestoneService._resolve_create_category —
        kept as a dedicated copy so the activity_service stays free of
        cross-service imports (matches the existing PMIS layering)."""
        is_published = (project.status or "").lower() == "published"
        if not is_published:
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
        """Same rules as MilestoneService._resolve_update_finance_fields:
          * category locked once set (mismatch → 409).
          * ccn_value editable only when row.category='ccn'.
          * cap displacement on update; bypassed when TPV=0.
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
