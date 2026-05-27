"""ActivityService — CRUD + dependency cycle guard + inline-comment / files."""
from __future__ import annotations

import re
from typing import List, Optional

# FE normalizes activity node.id to the WBS display code (e.g. "A1.2") after
# normalizeProject runs, so depends_on arrives as display codes rather than
# UUIDs. Bug #12: resolve them to UUIDs via milestone+activity position lookup.
_ACTIVITY_DISPLAY_CODE_RE = re.compile(r"^A(\d+)\.(\d+)$", re.IGNORECASE)

from sqlalchemy.orm import Session

from app.core.errors import (
    ActivityNotFoundError,
    DependencyCycleError,
    MilestoneNotFoundError,
    ValidationError,
)
from app.repositories.activity_repository import ActivityRepository
from app.repositories.comment_repository import CommentRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.activity import ActivityCreateRequest, ActivityUpdateRequest
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
from app.utilities.project_lock import assert_milestone_activity_writable
from app.utilities.vendor_resolver import assert_vendor_in_project


class ActivityService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ActivityRepository(db)
        self.milestones = MilestoneRepository(db)
        self.projects = ProjectRepository(db)
        self.comments = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)

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
        # Status validation is schema-level (2-value hardcoded set per
        # monolith parity); priority + ownerDivision are service-level
        # catalog checks; concerned_divisions accepted silently (no
        # catalog check on the wire — monolith parity).
        self._validate_priority(payload.priority)
        self._validate_owner_division(payload.owner_division)
        self._validate_concerned_divisions(payload.concerned_divisions)
        # Owner/concerned division "others" requires a free-text companion.
        from app.utilities.division_other_pair import (
            validate_owner_division_pair,
            validate_concerned_divisions_pair,
        )
        validate_owner_division_pair(
            owner_division=payload.owner_division,
            owner_division_other=payload.owner_division_other,
        )
        validate_concerned_divisions_pair(
            concerned_divisions=payload.concerned_divisions,
            concerned_division_other=payload.concerned_division_other,
        )
        # Vendor (when supplied) must be attached to the parent project.
        if payload.vendor_id:
            assert_vendor_in_project(
                self.db, project_id=milestone.project_id,
                vendor_id=payload.vendor_id,
            )
        # Date rules — parent floor is the owning milestone (monolith parity).
        validate_entity_dates(
            entity_start=payload.start_date,
            entity_end=payload.end_date,
            actual_start=payload.actual_start_date,
            actual_end=payload.actual_end_date,
            parent_start_date=milestone.start_date,
            project_start_date=project.start_date if project else None,
            entity_label="activity",
            parent_label="milestone",
        )
        position = (
            payload.position
            if payload.position is not None and payload.position > 0
            else self.repo.next_position_for_milestone(milestone_id)
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
            priority=payload.priority,
            owner_division=payload.owner_division,
            owner_division_other=payload.owner_division_other,
            concerned_divisions=payload.concerned_divisions,
            concerned_division_other=payload.concerned_division_other,
            vendor_id=payload.vendor_id,
            position=position,
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
        self.db.commit()
        return row

    def update(
        self, activity_id: str, payload: ActivityUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ):
        row = self.get_by_id(activity_id)
        updates = payload.model_dump(exclude_unset=True)
        depends_on = updates.pop("depends_on", None)
        touched = set(updates.keys())

        # ----- catalog + transition validations on touched fields ------
        # Status is schema-level — no service check.
        if "priority" in updates:
            self._validate_priority(updates["priority"])
        if "owner_division" in updates:
            self._validate_owner_division(updates["owner_division"])
        # concerned_divisions accepted silently (no catalog check).
        # Owner/concerned division "others" pair revalidation. Use the
        # UNTOUCHED sentinel for sides not present in the PATCH payload —
        # falls back to the existing DB value, so users can flip just one
        # side at a time without sending the other.
        if (
            "owner_division" in updates or "owner_division_other" in updates
            or "concerned_divisions" in updates or "concerned_division_other" in updates
        ):
            from app.utilities.division_other_pair import (
                UNTOUCHED,
                validate_owner_division_pair,
                validate_concerned_divisions_pair,
            )
            validate_owner_division_pair(
                owner_division=updates.get("owner_division", UNTOUCHED),
                owner_division_other=updates.get("owner_division_other", UNTOUCHED),
                existing_owner_division=row.owner_division,
                existing_owner_division_other=row.owner_division_other,
            )
            validate_concerned_divisions_pair(
                concerned_divisions=updates.get("concerned_divisions", UNTOUCHED),
                concerned_division_other=updates.get("concerned_division_other", UNTOUCHED),
                existing_concerned_divisions=row.concerned_divisions,
                existing_concerned_division_other=row.concerned_division_other,
            )
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
            project = self.projects.get_by_id(row.project_id)
            new_start = updates.get("start_date", row.start_date)
            new_end = updates.get("end_date", row.end_date)
            new_actual_start = updates.get("actual_start_date", row.actual_start_date)
            new_actual_end = updates.get("actual_end_date", row.actual_end_date)
            validate_entity_dates(
                entity_start=new_start,
                entity_end=new_end,
                actual_start=new_actual_start,
                actual_end=new_actual_end,
                parent_start_date=milestone.start_date if milestone else None,
                project_start_date=project.start_date if project else None,
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

    def _assert_deps_completed(self, activity_id: str) -> None:
        """Dependency-completion gate (monolith parity, _gate_status_against_deps).
        Block flipping an activity's status to ``completed`` while any of its
        dependency targets are still ``not_completed``. Mirrors monolith
        ``PMIS-OpenProject/app/api/v3/activities/services/update.py:88-118``.
        """
        from sqlalchemy import select
        from app.models.activity import Activity
        dep_ids = self.repo.list_dependencies_for(activity_id)
        if not dep_ids:
            return
        rows = self.db.execute(
            select(Activity.name, Activity.status)
            .where(Activity.id.in_(dep_ids))
            .where(Activity.deleted_at.is_(None))
        ).all()
        blockers = [name for name, status in rows if not is_terminal_status(status)]
        if not blockers:
            return
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
            row = self.db.execute(
                select(Activity.id)
                .join(Milestone, Milestone.id == Activity.milestone_id)
                .where(Milestone.project_id == project_id)
                .where(Milestone.position == ms_pos)
                .where(Milestone.deleted_at.is_(None))
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
            action="update", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "completed"},
                "auto_triggered": True,
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
