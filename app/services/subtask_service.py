"""SubtaskService — CRUD with Doc-24 unbounded nesting (parent_subtask_id),
dependency cycle guard, same-vendor assignment guard, and inline comment /
files on create.

Per user direction the nesting depth is UNCAPPED. The repo's recursive
descendant walk has its own cycle-safe seen-set so unbounded nesting is
safe for the cascade soft-delete / restore paths.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    CallerCannotModifyTargetError,
    DependencyCycleError,
    SubtaskNotFoundError,
    TaskNotFoundError,
    ValidationError,
)
from app.repositories.comment_repository import CommentRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.subtask_repository import SubtaskRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.subtask import SubtaskCreateRequest, SubtaskUpdateRequest
from app.utilities.catalogs import (
    active_priorities,
    is_known_priority,
    is_terminal_status,
)
from app.utilities.date_rules import validate_entity_dates
from app.utilities.project_lock import assert_task_subtask_writable


class SubtaskService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SubtaskRepository(db)
        self.tasks = TaskRepository(db)
        self.projects = ProjectRepository(db)
        self.comments = CommentRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def get_by_id(self, subtask_id: str):
        row = self.repo.get_by_id(subtask_id)
        if row is None:
            raise SubtaskNotFoundError("The subtask could not be found.")
        return row

    def list_for_task(
        self, task_id: str, *, offset=1, page_size=100,
        include_deleted=False, top_level_only=False,
    ):
        return self.repo.list_for_task(
            task_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted, top_level_only=top_level_only,
        )

    def create(
        self,
        payload: SubtaskCreateRequest,
        *,
        task_id: Optional[str] = None,
        parent_subtask_id: Optional[str] = None,
        caller_user_id: Optional[str],
        body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ):
        """Create a subtask. Exactly one of ``task_id`` /
        ``parent_subtask_id`` is provided (route layer enforces).
        """
        if (task_id is None) == (parent_subtask_id is None):
            raise ValidationError(
                "Exactly one of task_id or parent_subtask_id is required"
            )

        if parent_subtask_id is not None:
            parent = self.get_by_id(parent_subtask_id)
            resolved_task_id = parent.task_id
            project_id = parent.project_id
            position = (
                payload.position
                if payload.position is not None and payload.position > 0
                else self.repo.next_position_under_subtask(parent.id)
            )
            # Nested subtask: parent floor is the parent SUBTASK (monolith
            # parity — see PMIS-OpenProject/app/api/v3/subtasks/services/
            # create.py:219-226 which sets parent_label="subtask").
            parent_start_for_floor = parent.start_date
            parent_label_for_msg = "subtask"
        else:
            task = self.tasks.get_by_id(task_id)
            if task is None:
                raise TaskNotFoundError("The task could not be found.")
            resolved_task_id = task.id
            project_id = task.project_id
            position = (
                payload.position
                if payload.position is not None and payload.position > 0
                else self.repo.next_position_under_task(task.id)
            )
            # Top-level subtask: parent floor is the owning TASK.
            parent_start_for_floor = task.start_date
            parent_label_for_msg = "task"

        # Project-lock — subtasks require project status='published'.
        project = self.projects.get_by_id(project_id)
        assert_task_subtask_writable(project)
        # Priority catalog check.
        self._validate_priority(payload.priority)
        # Date rules — parent floor varies (task vs subtask) per the
        # parent type just resolved above.
        validate_entity_dates(
            entity_start=payload.start_date,
            entity_end=payload.end_date,
            actual_start=payload.actual_start_date,
            actual_end=payload.actual_end_date,
            parent_start_date=parent_start_for_floor,
            project_start_date=project.start_date if project else None,
            entity_label="subtask",
            parent_label=parent_label_for_msg,
        )

        if payload.assigned_to:
            self._validate_assignee(payload.assigned_to, project_id)

        row = self.repo.create(
            project_id=project_id,
            task_id=resolved_task_id,
            parent_subtask_id=parent_subtask_id,
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
            self._guard_dependency_cycle(row.id, payload.depends_on)
            self._assert_deps_in_same_project(row.project_id, payload.depends_on)
            self._assert_dep_dates_outlasting(row, payload.depends_on)
            self.repo.replace_dependencies(row.id, payload.depends_on)

        # Inline comment / attachments — written under the new subtask.
        # Captured on ``_inline_comment`` so the controller can echo the
        # comment back on the multipart-create response (monolith parity).
        body_clean = (body or "").strip() or None
        atts = list(attachments or [])
        row._inline_comment = None
        if body_clean or atts:
            row._inline_comment = self.comments.create(
                target_kind="subtask",
                target_id=row.id,
                author_user_id=caller_user_id,
                body=body_clean,
                attachments=atts or None,
            )

        self.audit.write(
            project_id=row.project_id,
            target_kind="subtask", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={
                "name": row.name,
                "task_id": row.task_id,
                "parent_subtask_id": row.parent_subtask_id,
            },
        )
        self.db.commit()
        return row

    def update(
        self, subtask_id: str, payload: SubtaskUpdateRequest,
        *, caller_user_id: Optional[str], request=None,
    ):
        row = self.get_by_id(subtask_id)
        # Project-lock — subtask writes require status='published'.
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
                self._assert_all_nested_subtasks_completed(row.id)
            if (
                not is_terminal_status(new_status)
                and is_terminal_status(row.status)
            ):
                self._assert_parent_not_completed(row)

        # Date-floor re-validation against the merged values. Parent
        # floor is the parent SUBTASK when this row is nested
        # (``parent_subtask_id`` is set), else the owning TASK.
        if (
            "start_date" in updates or "end_date" in updates
            or "actual_start_date" in updates or "actual_end_date" in updates
        ):
            if row.parent_subtask_id is not None:
                parent = self.get_by_id(row.parent_subtask_id)
                parent_start = parent.start_date
                parent_label = "subtask"
            else:
                task = self.tasks.get_by_id(row.task_id)
                parent_start = task.start_date if task else None
                parent_label = "task"
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
                parent_start_date=parent_start,
                project_start_date=project.start_date if project else None,
                entity_label="subtask",
                parent_label=parent_label,
            )
            self._assert_dep_dates_reverse(row, new_start, new_end)

        if "assigned_to" in updates and updates["assigned_to"] is not None:
            self._validate_assignee(updates["assigned_to"], row.project_id)

        if request is not None and touched:
            from app.core.permissions import SUBTASK_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=SUBTASK_FIELD_CODES,
                touched_fields=touched,
                scope_key=("project", row.project_id),
            )

        if updates:
            before = {k: getattr(row, k) for k in updates}
            self.repo.update(row, updated_by=caller_user_id, **updates)
            self.audit.write(
                project_id=row.project_id,
                target_kind="subtask", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={
                    k: {"before": before[k], "after": updates[k]}
                    for k in updates
                },
            )
        if depends_on is not None:
            self._guard_dependency_cycle(row.id, depends_on)
            if depends_on:
                self._assert_deps_in_same_project(row.project_id, depends_on)
                self._assert_dep_dates_outlasting(row, depends_on)
            self.repo.replace_dependencies(row.id, depends_on)
            self.audit.write(
                project_id=row.project_id,
                target_kind="subtask", target_id=row.id,
                action="update", actor_user_id=caller_user_id,
                changes={"depends_on": depends_on},
            )
        self.db.commit()
        return row

    def delete(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(subtask_id)
        # Monolith parity: block delete when any LIVE incoming dependency
        # from outside the cascade set still references this subtask or
        # any of its live descendants.
        self._assert_no_blocking_dependencies(row)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="subtask", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.repo.get_by_id(subtask_id, include_deleted=True)
        if row is None:
            raise SubtaskNotFoundError("The subtask could not be found.")
        # Monolith parity: a live (non-deleted) row reports the no-op
        # condition explicitly rather than silently returning the row.
        if row.deleted_at is None:
            raise ValidationError(
                "This subtask is already active and does not need to be restored."
            )
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="subtask", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    # ----------------------------------------------- dependency-block ---

    def _assert_no_blocking_dependencies(self, row) -> None:
        """Doc-31 dependency-block on delete: when this subtask (or any
        of its live descendants — nested subtasks cascade with it) is the
        TARGET of a live incoming dependency from OUTSIDE the cascade
        set, the delete is rejected.

        Matches monolith ``app/api/v3/subtasks/services/delete.py`` —
        422 ``ValidationError`` with ``_embedded.details.errorIdentifier
        = "dependency_block"`` plus a ``blockers`` array of
        ``{source, sourceKind, target, targetKind}`` rows. Display codes
        are used in the message + blockers list (not raw UUIDs) so the
        FE has something user-readable.
        """
        from app.models.subtask import Subtask
        from app.models.subtask_dependency import SubtaskDependency

        # Build the cascade set = {root} ∪ {all live descendants}.
        cascade_ids = {row.id}
        frontier = [row.id]
        while frontier:
            parent_id = frontier.pop()
            child_ids = list(self.db.execute(
                select(Subtask.id)
                .where(Subtask.parent_subtask_id == parent_id)
                .where(Subtask.deleted_at.is_(None))
            ).scalars())
            for cid in child_ids:
                if cid not in cascade_ids:
                    cascade_ids.add(cid)
                    frontier.append(cid)

        # Live deps where target IS in cascade but source IS NOT — i.e.,
        # external rows that still depend on something inside this delete.
        dep_rows = list(self.db.execute(
            select(SubtaskDependency.from_subtask_id, SubtaskDependency.to_subtask_id)
            .join(Subtask, Subtask.id == SubtaskDependency.from_subtask_id)
            .where(SubtaskDependency.to_subtask_id.in_(cascade_ids))
            .where(Subtask.deleted_at.is_(None))
        ).all())
        external = [
            (src, dst) for src, dst in dep_rows if src not in cascade_ids
        ]
        if not external:
            return

        # Resolve source/target to display codes for the message + blockers.
        all_ids = {src for src, _ in external} | {dst for _, dst in external}
        codes = self._batch_resolve_display_codes(list(all_ids))
        blockers = [
            {
                "source": codes.get(src, src),
                "sourceKind": "subtask",
                "target": codes.get(dst, dst),
                "targetKind": "subtask",
            }
            for src, dst in external
        ]
        listed = ", ".join(
            f"{b['source']} (depends on {b['target']})" for b in blockers[:5]
        )
        more = f" and {len(blockers) - 5} more" if len(blockers) > 5 else ""
        raise ValidationError(
            f"Cannot delete subtask '{row.name}' — the following live "
            f"dependencies must be removed first: {listed}{more}.",
            details={
                "errorIdentifier": "dependency_block",
                "rootKind": "subtask",
                "rootLabel": row.name,
                "blockers": blockers,
            },
        )

    def _batch_resolve_display_codes(self, subtask_ids: List[str]) -> dict:
        """Return ``{subtask_id: 'S<m>.<a>.<t>.<chain>'}`` for the given
        subtask UUIDs. Walks parent_subtask_id chain per row to build the
        nesting suffix (5+ segments for nested subtasks)."""
        if not subtask_ids:
            return {}
        from app.models.activity import Activity
        from app.models.milestone import Milestone
        from app.models.subtask import Subtask
        from app.models.task import Task

        # Pull every (id, position, parent_subtask_id, task_id) — both for
        # the requested IDs and any ancestor we may walk up to. Simplest:
        # one query per project's whole subtask set is overkill, so just
        # query rows by id and walk up lazily.
        rows = {
            sid: (pos, parent_id, task_id)
            for sid, pos, parent_id, task_id in self.db.execute(
                select(
                    Subtask.id, Subtask.position,
                    Subtask.parent_subtask_id, Subtask.task_id,
                )
                .where(Subtask.id.in_(subtask_ids))
            ).all()
        }
        ancestor_ids: set[str] = set()
        for sid, (_, parent_id, _) in rows.items():
            cur = parent_id
            while cur:
                ancestor_ids.add(cur)
                # Pre-fetch ancestor positions in a moment.
                cur_row = self.db.execute(
                    select(Subtask.parent_subtask_id)
                    .where(Subtask.id == cur)
                ).first()
                cur = cur_row[0] if cur_row else None
        if ancestor_ids:
            ancestor_rows = self.db.execute(
                select(Subtask.id, Subtask.position, Subtask.parent_subtask_id)
                .where(Subtask.id.in_(ancestor_ids))
            ).all()
            for aid, pos, parent_id in ancestor_rows:
                if aid not in rows:
                    rows[aid] = (pos, parent_id, None)

        # Per-task M.A.T chain.
        task_ids = {tid for _, _, tid in rows.values() if tid}
        chains = {}
        if task_ids:
            chain_rows = self.db.execute(
                select(
                    Task.id, Milestone.position,
                    Activity.position, Task.position,
                )
                .join(Activity, Activity.id == Task.activity_id)
                .join(Milestone, Milestone.id == Activity.milestone_id)
                .where(Task.id.in_(task_ids))
            ).all()
            chains = {tid: (m, a, t) for tid, m, a, t in chain_rows}

        out = {}
        for sid in subtask_ids:
            r = rows.get(sid)
            if not r:
                continue
            pos, parent_id, task_id = r
            chain = chains.get(task_id)
            if not chain or not all(chain) or not pos:
                continue
            m_pos, a_pos, t_pos = chain
            positions = [pos]
            cur = parent_id
            seen: set[str] = set()
            while cur and cur not in seen:
                seen.add(cur)
                anc = rows.get(cur)
                if not anc:
                    break
                anc_pos, anc_parent, _ = anc
                if not anc_pos:
                    break
                positions.insert(0, anc_pos)
                cur = anc_parent
            parts = [f"S{m_pos}", str(a_pos), str(t_pos)] + [str(p) for p in positions]
            out[sid] = ".".join(parts)
        return out

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

    def _assert_all_nested_subtasks_completed(self, subtask_id: str) -> None:
        """Children-completion gate for subtasks (nested subtasks roll up
        to the immediate parent)."""
        from app.models.subtask import Subtask
        rows = self.db.execute(
            select(Subtask.name, Subtask.status)
            .where(Subtask.parent_subtask_id == subtask_id)
            .where(Subtask.deleted_at.is_(None))
        ).all()
        pending = [name for name, status in rows if not is_terminal_status(status)]
        if not pending:
            return
        # Monolith parity: each name is wrapped in single quotes.
        names = ", ".join(f"'{n}'" for n in pending[:5])
        more = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
        plural = "s are" if len(pending) > 1 else " is"
        raise ValidationError(
            f"Cannot mark this subtask as completed — the following "
            f"nested subtask{plural} not yet completed: {names}{more}."
        )

    def _assert_parent_not_completed(self, row) -> None:
        """Parent-revert gate: nested subtasks check their parent
        subtask; top-level subtasks check their owning task."""
        if row.parent_subtask_id is not None:
            parent = self.get_by_id(row.parent_subtask_id)
            if parent is None or not is_terminal_status(parent.status):
                return
            raise ValidationError(
                f"Cannot revert this subtask to not_completed — its "
                f"parent subtask '{parent.name}' is still completed. "
                f"Revert the parent subtask first."
            )
        task = self.tasks.get_by_id(row.task_id)
        if task is None or not is_terminal_status(task.status):
            return
        raise ValidationError(
            f"Cannot revert this subtask to not_completed — its parent "
            f"task '{task.name}' is still completed. Revert the parent "
            f"task first."
        )

    def _assert_deps_in_same_project(
        self, project_id: str, depends_on_ids: List[str],
    ) -> None:
        if not depends_on_ids:
            return
        from app.models.subtask import Subtask
        rows = self.db.execute(
            select(Subtask.id)
            .where(Subtask.id.in_(depends_on_ids))
            .where(Subtask.project_id == project_id)
            .where(Subtask.deleted_at.is_(None))
        ).all()
        found = {r[0] for r in rows}
        missing = [d for d in depends_on_ids if d not in found]
        if missing:
            raise ValidationError(
                f"Unknown or out-of-project subtask dependency target(s): "
                f"{', '.join(missing)}"
            )

    def _assert_dep_dates_outlasting(
        self, source_row, depends_on_ids: List[str],
    ) -> None:
        if not depends_on_ids:
            return
        from app.models.subtask import Subtask
        from app.utilities.dep_date_rules import (
            collect_forward_violations,
            raise_forward_if_violations,
        )
        # Monolith parity: dep target labels use the displayCode chain
        # (``S1.1.1.1`` etc.), NOT the entity name. Resolve via the same
        # helper the dep-block guard uses.
        rows = self.db.execute(
            select(Subtask.id, Subtask.start_date, Subtask.end_date)
            .where(Subtask.id.in_(depends_on_ids))
        ).all()
        codes = self._batch_resolve_display_codes([r[0] for r in rows])
        targets = [(codes.get(sid, sid), s, e) for sid, s, e in rows]
        starts, ends = collect_forward_violations(
            source_start=source_row.start_date,
            source_end=source_row.end_date,
            targets=targets,
        )
        raise_forward_if_violations(
            starts, ends,
            # Monolith parity: prefix with kind so message reads
            # ``Subtask '<name>' cannot end on …``.
            source_label=f"Subtask '{source_row.name}'",
            source_start=source_row.start_date,
            source_end=source_row.end_date,
            kind_singular="subtask",
        )

    def _assert_dep_dates_reverse(
        self, target_row, new_start, new_end,
    ) -> None:
        from app.models.subtask import Subtask
        from app.models.subtask_dependency import SubtaskDependency
        from app.utilities.dep_date_rules import (
            collect_reverse_violations,
            raise_reverse_if_violations,
        )
        rows = self.db.execute(
            select(Subtask.name, Subtask.start_date, Subtask.end_date)
            .join(SubtaskDependency, SubtaskDependency.from_subtask_id == Subtask.id)
            .where(SubtaskDependency.to_subtask_id == target_row.id)
            .where(Subtask.deleted_at.is_(None))
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
            target_label=f"Subtask '{target_row.name}'",
            target_start=new_start,
            target_end=new_end,
            kind_singular="subtask",
        )

    # ----------------------------------------------------- dep cycle -----

    def _guard_dependency_cycle(
        self, subtask_id: str, depends_on_ids: List[str],
    ) -> None:
        """Monolith parity: rejected as 422 ``ValidationError`` (not 409
        ``DependencyCycleError``) with message
        ``"Adding dependency on '<uuid>' would create a cycle."`` —
        ``<uuid>`` is the *root* dependency entry that closes the cycle.
        """
        # Self-loop: the offender is the subtask itself.
        for d in depends_on_ids:
            if d == subtask_id:
                raise ValidationError(
                    f"Adding dependency on '{d}' would create a cycle."
                )
        visited: set[str] = set()
        # Frontier carries (root_dep, current_node) so when we detect the
        # cycle we can name the user-supplied dependency that caused it.
        frontier: List[tuple] = [(d, d) for d in depends_on_ids]
        while frontier:
            root_dep, current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            for nxt in self.repo.list_dependencies_for(current):
                if nxt == subtask_id:
                    raise ValidationError(
                        f"Adding dependency on '{root_dep}' would create a cycle."
                    )
                frontier.append((root_dep, nxt))

    def _validate_assignee(self, assignee_user_id: str, project_id: str) -> None:
        """Round-7 Q9: same invariants as ``TaskService._validate_assignee``."""
        from app.models._cross_schema import (
            User as MirrorUser,
            UserRoleAssignment as MirrorURA,
        )
        from app.models.project_vendor import ProjectVendor

        assignee = self.db.execute(
            select(MirrorUser).where(MirrorUser.id == assignee_user_id)
        ).scalar_one_or_none()
        if assignee is None:
            # Monolith parity: terse, quoted-UUID message at 422 (same
            # shape as TaskService).
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
