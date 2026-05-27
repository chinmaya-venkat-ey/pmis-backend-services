"""TaskService — CRUD + dependency cycle guard + same-vendor assignment
guard + inline-comment / files."""
from __future__ import annotations

import re
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session


# FE normalizes task node.id to the WBS display code (e.g. "T1.2.3") after
# normalizeProject runs, so depends_on arrives as display codes rather than
# UUIDs. Mirror of the milestone + activity resolvers; tasks use
# T{milestone_position}.{activity_position}.{task_position} format.
_TASK_DISPLAY_CODE_RE = re.compile(r"^T(\d+)\.(\d+)\.(\d+)$", re.IGNORECASE)

from app.core.errors import (
    ActivityNotFoundError,
    CallerCannotModifyTargetError,
    DependencyCycleError,
    TaskNotFoundError,
    ValidationError,
)
from app.repositories.activity_repository import ActivityRepository
from app.repositories.comment_repository import CommentRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreateRequest, TaskUpdateRequest
from app.utilities.catalogs import (
    active_priorities,
    is_known_priority,
    is_terminal_status,
)
from app.utilities.date_rules import validate_entity_dates
from app.utilities.project_lock import assert_task_subtask_writable


class TaskService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TaskRepository(db)
        self.activities = ActivityRepository(db)
        self.projects = ProjectRepository(db)
        self.comments = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def get_by_id(self, task_id: str):
        row = self.repo.get_by_id(task_id)
        if row is None:
            raise TaskNotFoundError("The task could not be found.")
        return row

    def list_for_activity(
        self, activity_id: str, *, offset=1, page_size=50, include_deleted=False,
    ):
        return self.repo.list_for_activity(
            activity_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted,
        )

    def create(
        self, activity_id: str, payload: TaskCreateRequest,
        *, caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        activity = self.activities.get_by_id(activity_id)
        if activity is None:
            raise ActivityNotFoundError("The activity could not be found.")
        # Project-lock — tasks may only be written on a PUBLISHED project.
        project = self.projects.get_by_id(activity.project_id)
        assert_task_subtask_writable(project)
        # Priority catalog check.
        self._validate_priority(payload.priority)
        # Date rules — parent floor is the owning activity (monolith parity).
        validate_entity_dates(
            entity_start=payload.start_date,
            entity_end=payload.end_date,
            actual_start=payload.actual_start_date,
            actual_end=payload.actual_end_date,
            parent_start_date=activity.start_date,
            project_start_date=project.start_date if project else None,
            entity_label="task",
            parent_label="activity",
        )
        if payload.assigned_to:
            self._validate_assignee(payload.assigned_to, activity.project_id)
        position = (
            payload.position
            if payload.position is not None and payload.position > 0
            else self.repo.next_position_for_activity(activity_id)
        )
        row = self.repo.create(
            project_id=activity.project_id,
            activity_id=activity_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            actual_start_date=payload.actual_start_date,
            actual_end_date=payload.actual_end_date,
            status=payload.status,
            priority=payload.priority,
            assigned_to=payload.assigned_to,
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

        # Inline comment / attachments — written under the new task.
        # Captured on ``_inline_comment`` so the controller can echo the
        # comment back on the multipart-create response (monolith parity).
        body_clean = (body or "").strip() or None
        atts = list(attachments or [])
        row._inline_comment = None
        if body_clean or atts:
            row._inline_comment = self.comments.create(
                target_kind="task",
                target_id=row.id,
                author_user_id=caller_user_id,
                body=body_clean,
                attachments=atts or None,
            )

        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "activity_id": row.activity_id},
        )
        # Reverse cascade: new (not_completed) task invalidates any
        # auto-completed ancestor.
        self._cascade_revert_from_new_child(row, caller_user_id=caller_user_id)
        self.db.commit()
        return row

    def update(
        self, task_id: str, payload: TaskUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ):
        row = self.get_by_id(task_id)
        # Project-lock — task writes require status='published'.
        project = self.projects.get_by_id(row.project_id)
        assert_task_subtask_writable(project)
        updates = payload.model_dump(exclude_unset=True)
        depends_on = updates.pop("depends_on", None)
        touched = set(updates.keys())

        # Priority catalog + status-completion + parent-revert gates.
        if "priority" in updates:
            self._validate_priority(updates["priority"])
        if "status" in updates and updates["status"] is not None:
            new_status = updates["status"]
            if is_terminal_status(new_status) and not is_terminal_status(row.status):
                self._assert_deps_completed(row.id)
                self._assert_all_child_subtasks_completed(row.id)
            if (
                not is_terminal_status(new_status)
                and is_terminal_status(row.status)
            ):
                self._assert_parent_activity_not_completed(row.activity_id)

        # Date-floor re-validation against the merged values.
        if (
            "start_date" in updates or "end_date" in updates
            or "actual_start_date" in updates or "actual_end_date" in updates
        ):
            activity = self.activities.get_by_id(row.activity_id)
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
                parent_start_date=activity.start_date if activity else None,
                project_start_date=project.start_date if project else None,
                entity_label="task",
                parent_label="activity",
            )
            self._assert_dep_dates_reverse(row, new_start, new_end)

        if "assigned_to" in updates and updates["assigned_to"] is not None:
            self._validate_assignee(updates["assigned_to"], row.project_id)

        if request is not None and touched:
            from app.core.permissions import TASK_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=TASK_FIELD_CODES,
                touched_fields=touched,
                scope_key=("project", row.project_id),
            )

        if updates:
            before = {k: getattr(row, k) for k in updates}
            self.repo.update(row, updated_by=caller_user_id, **updates)
            self.audit.write(
                project_id=row.project_id,
                target_kind="task", target_id=row.id,
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
                target_kind="task", target_id=row.id,
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

    def delete(self, task_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(task_id)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, task_id: str, *, caller_user_id: Optional[str]):
        row = self.repo.get_by_id(task_id, include_deleted=True)
        if row is None:
            raise TaskNotFoundError("The task could not be found.")
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    # ----------------------------------------------- catalog + gates -----

    def _validate_priority(self, priority: Optional[str]) -> None:
        if priority is None:
            return
        if is_known_priority(self.db, priority):
            return
        allowed = active_priorities(self.db)
        raise ValidationError(
            f"Priority must be one of: {', '.join(allowed)}."
        )

    def _assert_deps_in_same_project(
        self, project_id: str, depends_on_ids: List[str],
    ) -> None:
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.task import Task
        rows = self.db.execute(
            select(Task.id)
            .where(Task.id.in_(depends_on_ids))
            .where(Task.project_id == project_id)
            .where(Task.deleted_at.is_(None))
        ).all()
        found = {r[0] for r in rows}
        missing = [d for d in depends_on_ids if d not in found]
        if missing:
            raise ValidationError(
                f"Unknown or out-of-project task dependency target(s): "
                f"{', '.join(missing)}"
            )

    def _assert_dep_dates_outlasting(
        self, source_row, depends_on_ids: List[str],
    ) -> None:
        if not depends_on_ids:
            return
        from sqlalchemy import select
        from app.models.task import Task
        from app.utilities.dep_date_rules import (
            collect_forward_violations,
            raise_forward_if_violations,
        )
        rows = self.db.execute(
            select(Task.name, Task.start_date, Task.end_date)
            .where(Task.id.in_(depends_on_ids))
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
            kind_singular="task",
        )

    def _assert_dep_dates_reverse(
        self, target_row, new_start, new_end,
    ) -> None:
        from sqlalchemy import select
        from app.models.task import Task
        from app.models.task_dependency import TaskDependency
        from app.utilities.dep_date_rules import (
            collect_reverse_violations,
            raise_reverse_if_violations,
        )
        rows = self.db.execute(
            select(Task.name, Task.start_date, Task.end_date)
            .join(TaskDependency, TaskDependency.from_task_id == Task.id)
            .where(TaskDependency.to_task_id == target_row.id)
            .where(Task.deleted_at.is_(None))
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
            target_label=f"Task '{target_row.name}'",
            target_start=new_start,
            target_end=new_end,
            kind_singular="task",
        )

    def _assert_deps_completed(self, task_id: str) -> None:
        """Dependency-completion gate (monolith parity). Block flipping a
        task to ``completed`` while any of its dependency targets are still
        ``not_completed``."""
        from sqlalchemy import select
        from app.models.task import Task
        dep_ids = self.repo.list_dependencies_for(task_id)
        if not dep_ids:
            return
        rows = self.db.execute(
            select(Task.name, Task.status)
            .where(Task.id.in_(dep_ids))
            .where(Task.deleted_at.is_(None))
        ).all()
        blockers = [name for name, status in rows if not is_terminal_status(status)]
        if not blockers:
            return
        names = ", ".join(f"'{n}'" for n in blockers[:3])
        more = f" (+{len(blockers) - 3} more)" if len(blockers) > 3 else ""
        raise ValidationError(
            f"Cannot mark this task as completed — the following "
            f"dependency target(s) are not yet completed: {names}{more}."
        )

    def _assert_all_child_subtasks_completed(self, task_id: str) -> None:
        """Children-completion gate for tasks. Walks every TOP-LEVEL
        subtask under this task (nested subtasks roll up to their
        top-level parent — checked separately by ``SubtaskService``)."""
        from sqlalchemy import select
        from app.models.subtask import Subtask
        rows = self.db.execute(
            select(Subtask.name, Subtask.status)
            .where(Subtask.task_id == task_id)
            .where(Subtask.parent_subtask_id.is_(None))
            .where(Subtask.deleted_at.is_(None))
        ).all()
        pending = [name for name, status in rows if not is_terminal_status(status)]
        if not pending:
            return
        names = ", ".join(pending[:5])
        more = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
        plural = "s are" if len(pending) > 1 else " is"
        raise ValidationError(
            f"Cannot mark this task as completed — the following child "
            f"subtask{plural} not yet completed: {names}{more}."
        )

    def _assert_parent_activity_not_completed(self, activity_id: str) -> None:
        """Parent-revert gate: can't revert a task to ``not_completed``
        while its parent activity is still completed."""
        a = self.activities.get_by_id(activity_id)
        if a is None or not is_terminal_status(a.status):
            return
        raise ValidationError(
            f"Cannot revert this task to not_completed — its parent "
            f"activity '{a.name}' is still completed. Revert the parent "
            f"activity first."
        )

    # ------------------------------------------ display-code resolver -----

    def _resolve_depends_on(
        self, project_id: str, raw_ids: List[str],
    ) -> List[str]:
        """Resolve display codes (e.g. 'T1.2.3') mixed with UUIDs to UUIDs.

        The FE normalizes task node.id to serverDisplayCode (T{ms}.{act}.{tsk})
        via normalizeProject, so depends_on arrives as display codes. Mirror
        of MilestoneService / ActivityService — tasks use
        T{milestone_position}.{activity_position}.{task_position} format.
        """
        if not raw_ids:
            return []
        from app.models.activity import Activity
        from app.models.milestone import Milestone
        from app.models.task import Task

        lookups: List[tuple] = []
        uuid_ids: List[str] = []
        for dep_id in raw_ids:
            match = _TASK_DISPLAY_CODE_RE.match(dep_id)
            if match:
                lookups.append(
                    (int(match.group(1)), int(match.group(2)), int(match.group(3)))
                )
            else:
                uuid_ids.append(dep_id)

        resolved = list(uuid_ids)
        for ms_pos, act_pos, task_pos in lookups:
            row = self.db.execute(
                select(Task.id)
                .join(Activity, Activity.id == Task.activity_id)
                .join(Milestone, Milestone.id == Activity.milestone_id)
                .where(Milestone.project_id == project_id)
                .where(Milestone.position == ms_pos)
                .where(Milestone.deleted_at.is_(None))
                .where(Activity.position == act_pos)
                .where(Activity.deleted_at.is_(None))
                .where(Task.position == task_pos)
                .where(Task.deleted_at.is_(None))
            ).scalar_one_or_none()
            if row:
                resolved.append(row)
        return resolved

    # ----------------------------------------------------- dep cycle -----

    def _guard_dependency_cycle(self, task_id: str, depends_on_ids: List[str]) -> None:
        if task_id in depends_on_ids:
            raise DependencyCycleError("A task cannot depend on itself")
        visited: set[str] = set()
        frontier = list(depends_on_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == task_id:
                raise DependencyCycleError("Proposed dependencies form a cycle")
            frontier.extend(self.repo.list_dependencies_for(current))

    def _validate_assignee(self, assignee_user_id: str, project_id: str) -> None:
        """Round-7 Q9: enforce 4 invariants when setting/changing assigned_to.

          1. The user row exists in users.users.
          2. The user is not soft-deleted.
          3. The user's vendor_id matches a vendor mapped to the parent project.
          4. The user has at least one role-assignment on this project,
             either explicit (project_id) or via vendor-projection (org_id
             in the project's vendor set).
        """
        from app.models._cross_schema import (
            User as MirrorUser,
            UserRoleAssignment as MirrorURA,
        )
        from app.models.project_vendor import ProjectVendor

        assignee = self.db.execute(
            select(MirrorUser).where(MirrorUser.id == assignee_user_id)
        ).scalar_one_or_none()
        if assignee is None:
            # Monolith parity: terse, quoted-UUID message at 422.
            raise ValidationError(
                f"assignedTo user '{assignee_user_id}' does not exist."
            )
        if assignee.deleted_at is not None:
            raise CallerCannotModifyTargetError(
                "Assignee is soft-deleted",
                details={"check": "user_not_deleted", "assigned_to": assignee_user_id},
            )
        project_vendor_ids = list(self.db.execute(
            select(ProjectVendor.vendor_id).where(ProjectVendor.project_id == project_id)
        ).scalars())
        if assignee.vendor_id is None or assignee.vendor_id not in project_vendor_ids:
            raise CallerCannotModifyTargetError(
                "Assignee's vendor is not mapped to this project",
                details={
                    "check": "same_vendor",
                    "assigned_to": assignee_user_id,
                    "assignee_vendor_id": assignee.vendor_id,
                    "project_vendor_ids": project_vendor_ids,
                },
            )
        has_explicit = self.db.execute(
            select(MirrorURA.id)
            .where(MirrorURA.user_id == assignee_user_id)
            .where(MirrorURA.project_id == project_id)
            .limit(1)
        ).first()
        if has_explicit:
            return
        has_org_scoped = self.db.execute(
            select(MirrorURA.id)
            .where(MirrorURA.user_id == assignee_user_id)
            .where(MirrorURA.organization_id.in_(project_vendor_ids))
            .limit(1)
        ).first()
        if has_org_scoped:
            return
        raise CallerCannotModifyTargetError(
            "Assignee has no role-assignment on this project (explicit or via vendor)",
            details={
                "check": "project_membership",
                "assigned_to": assignee_user_id,
                "project_id": project_id,
            },
        )

    # ------------------------------------------ auto-complete cascade ----

    def _attempt_auto_complete(
        self, row, *, caller_user_id: Optional[str],
        triggering_child_id: Optional[str],
    ) -> None:
        """Best-effort auto-complete of this task when invoked by a child
        subtask's cascade. Silent no-op if already terminal, any live
        top-level subtask is non-terminal, or own deps not satisfied.
        On success, propagates upward to the activity.
        """
        if is_terminal_status(row.status):
            return
        if not self._all_live_top_level_subtasks_terminal(row.id):
            return
        try:
            self._assert_deps_completed(row.id)
        except ValidationError:
            return
        before = row.status
        self.repo.update(row, status="completed", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=row.id,
            action="auto_complete", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "completed"},
                "by_child": triggering_child_id,
            },
        )
        self._cascade_to_parent(row, caller_user_id=caller_user_id)

    def _cascade_to_parent(self, row, *, caller_user_id: Optional[str]) -> None:
        """Walk one step up: task -> parent activity. Defers to
        ActivityService for the actual auto-complete attempt.
        """
        from app.services.activity_service import ActivityService
        act_service = ActivityService(self.db)
        act = act_service.repo.get_by_id(row.activity_id)
        if act is not None:
            act_service._attempt_auto_complete(
                act, caller_user_id=caller_user_id,
                triggering_child_id=row.id,
            )

    def _all_live_top_level_subtasks_terminal(self, task_id: str) -> bool:
        """True iff the task has at least one live top-level subtask AND
        every live top-level subtask is terminal. False on empty (a task
        without any subtasks should NOT auto-complete from an empty
        rollup — the user has to mark it manually)."""
        from app.models.subtask import Subtask
        rows = list(self.db.execute(
            select(Subtask.status)
            .where(Subtask.task_id == task_id)
            .where(Subtask.parent_subtask_id.is_(None))
            .where(Subtask.deleted_at.is_(None))
        ).all())
        if not rows:
            return False
        return all(is_terminal_status(status) for (status,) in rows)

    # --------------------------------------- reverse cascade (Q9) ---------

    def _cascade_revert_from_new_child(
        self, child_row, *, caller_user_id: Optional[str],
    ) -> None:
        """A newly-created task is not_completed. If its parent activity
        is terminal, auto-revert that activity and recurse upward.
        """
        from app.services.activity_service import ActivityService
        act_service = ActivityService(self.db)
        act = act_service.repo.get_by_id(child_row.activity_id)
        if act is not None and is_terminal_status(act.status):
            act_service._auto_revert(
                act, caller_user_id=caller_user_id,
                triggering_child_id=child_row.id,
            )

    def _auto_revert(
        self, row, *, caller_user_id: Optional[str],
        triggering_child_id: Optional[str],
    ) -> None:
        """Flip a terminal task back to not_completed, audit, recurse up.
        Called by SubtaskService when a new subtask is added under a
        completed task.
        """
        if not is_terminal_status(row.status):
            return
        before = row.status
        self.repo.update(row, status="not_completed", updated_by=caller_user_id)
        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=row.id,
            action="auto_revert", actor_user_id=caller_user_id,
            changes={
                "status": {"before": before, "after": "not_completed"},
                "by_child": triggering_child_id,
            },
        )
        self._cascade_revert_from_new_child(row, caller_user_id=caller_user_id)
