"""TaskService — CRUD + resource sidecar + dependency cycle guard +
round-7 Q9 same-vendor assignment validation."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    ActivityNotFoundError,
    CallerCannotModifyTargetError,
    DependencyCycleError,
    TaskNotFoundError,
)
from app.repositories.activity_repository import ActivityRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreateRequest, TaskUpdateRequest


class TaskService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TaskRepository(db)
        self.activities = ActivityRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def get_by_id(self, task_id: str):
        row = self.repo.get_by_id(task_id)
        if row is None:
            raise TaskNotFoundError(f"Task {task_id!r} not found")
        return row

    def list_for_activity(self, activity_id: str, *, offset=1, page_size=50, include_deleted=False):
        return self.repo.list_for_activity(
            activity_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    def create(self, payload: TaskCreateRequest, *, caller_user_id: Optional[str]):
        activity = self.activities.get_by_id(payload.activity_id)
        if activity is None:
            raise ActivityNotFoundError(f"Activity {payload.activity_id!r} not found")
        # Round-7 Q9: validate assignee at create time too.
        if payload.assigned_to:
            self._validate_assignee(payload.assigned_to, activity.project_id)
        position = self.repo.next_position_for_activity(payload.activity_id)
        row = self.repo.create(
            project_id=activity.project_id,
            activity_id=payload.activity_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            priority=payload.priority,
            assigned_to=payload.assigned_to,
            position=position,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if payload.depends_on:
            self._guard_dependency_cycle(row.id, payload.depends_on)
            self.repo.replace_dependencies(row.id, payload.depends_on)
        if payload.resource is not None:
            self.repo.upsert_resource(
                task_id=row.id, project_id=row.project_id,
                **payload.resource.model_dump(exclude_unset=True),
            )
        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "activity_id": row.activity_id},
        )
        self.db.commit()
        return row

    def update(self, task_id: str, payload: TaskUpdateRequest, *, caller_user_id: Optional[str], request=None):
        row = self.get_by_id(task_id)
        updates = payload.model_dump(exclude_unset=True, exclude={"resource"})
        touched = set(updates.keys())
        if payload.resource is not None:
            touched.add("resource")

        # Round-7 Q9: same-vendor + project-membership check on assigned_to.
        # Uniform — admin-tier callers also subject to this rule.
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
                changes={k: {"before": before[k], "after": updates[k]} for k in updates},
            )
        if payload.resource is not None:
            self.repo.upsert_resource(
                task_id=row.id, project_id=row.project_id,
                **payload.resource.model_dump(exclude_unset=True),
            )
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
        row = self.get_by_id(task_id)
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def replace_dependencies(self, task_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row = self.get_by_id(task_id)
        self._guard_dependency_cycle(task_id, depends_on_ids)
        self.repo.replace_dependencies(task_id, depends_on_ids)
        self.audit.write(
            project_id=row.project_id,
            target_kind="task", target_id=task_id,
            action="update", actor_user_id=caller_user_id,
            changes={"depends_on": depends_on_ids},
        )
        self.db.commit()
        return row, depends_on_ids

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
          2. The user is not soft-deleted (users.users.deleted_at IS NULL).
          3. The user's vendor_id matches a vendor mapped to the parent
             project via project.project_vendors. (Uniform — admin-tier
             callers are also subject to this check, per user direction.)
          4. The user has at least a project_member-equivalent grant on
             this project: either an explicit user_role_assignments row
             with project_id=<project_id>, OR an org-scoped role-assignment
             on a vendor mapped to this project (vendor->project projection).

        Reads from the cross-schema mirrors. Raises CallerCannotModifyTargetError
        with a structured `details` dict naming which check failed.
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
            raise CallerCannotModifyTargetError(
                "Assignee not found",
                details={"check": "user_exists", "assigned_to": assignee_user_id},
            )
        if assignee.deleted_at is not None:
            raise CallerCannotModifyTargetError(
                "Assignee is soft-deleted",
                details={"check": "user_not_deleted", "assigned_to": assignee_user_id},
            )
        # Vendor match: collect project's vendor mapping.
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
        # Project-role: explicit (project_id) OR org-scoped on a vendor
        # mapped to the project.
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
