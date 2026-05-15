"""SubtaskService — CRUD + Doc-24 nesting-depth cap + cycle guard.

settings.subtask_max_nesting_depth caps how deep the parent chain can go.
Default 5; configurable per env.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import (
    CallerCannotModifyTargetError,
    DependencyCycleError,
    SubtaskNestingDepthExceededError,
    SubtaskNotFoundError,
    TaskNotFoundError,
)
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.subtask_repository import SubtaskRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.subtask import SubtaskCreateRequest, SubtaskUpdateRequest


class SubtaskService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SubtaskRepository(db)
        self.tasks = TaskRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def get_by_id(self, subtask_id: str):
        row = self.repo.get_by_id(subtask_id)
        if row is None:
            raise SubtaskNotFoundError(f"Subtask {subtask_id!r} not found")
        return row

    def list_for_task(self, task_id: str, *, offset=1, page_size=100, include_deleted=False, top_level_only=False):
        return self.repo.list_for_task(
            task_id, offset=offset, page_size=page_size,
            include_deleted=include_deleted, top_level_only=top_level_only,
        )

    def create(self, payload: SubtaskCreateRequest, *, caller_user_id: Optional[str]):
        if payload.parent_subtask_id is None and payload.task_id is None:
            raise SubtaskNotFoundError("Either task_id or parent_subtask_id is required")

        if payload.parent_subtask_id is not None:
            parent = self.get_by_id(payload.parent_subtask_id)
            depth = self.repo.nesting_depth(parent.id) + 1
            if depth > settings.subtask_max_nesting_depth:
                raise SubtaskNestingDepthExceededError(
                    f"Subtask nesting depth would exceed max ({settings.subtask_max_nesting_depth})",
                    details={"depth": depth, "max": settings.subtask_max_nesting_depth},
                )
            task_id = parent.task_id
            project_id = parent.project_id
            position = self.repo.next_position_under_subtask(parent.id)
        else:
            task = self.tasks.get_by_id(payload.task_id)
            if task is None:
                raise TaskNotFoundError(f"Task {payload.task_id!r} not found")
            task_id = task.id
            project_id = task.project_id
            position = self.repo.next_position_under_task(task.id)

        # Round-7 Q9: validate assignee at create time too.
        if payload.assigned_to:
            self._validate_assignee(payload.assigned_to, project_id)

        row = self.repo.create(
            project_id=project_id,
            task_id=task_id,
            parent_subtask_id=payload.parent_subtask_id,
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
                subtask_id=row.id, project_id=row.project_id,
                **payload.resource.model_dump(exclude_unset=True),
            )
        self.audit.write(
            project_id=row.project_id,
            target_kind="subtask", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "task_id": row.task_id, "parent_subtask_id": row.parent_subtask_id},
        )
        self.db.commit()
        return row

    def update(self, subtask_id: str, payload: SubtaskUpdateRequest, *, caller_user_id: Optional[str], request=None):
        row = self.get_by_id(subtask_id)
        updates = payload.model_dump(exclude_unset=True, exclude={"resource"})
        touched = set(updates.keys())
        if payload.resource is not None:
            touched.add("resource")

        # Round-7 Q9: same-vendor + project-membership check on assigned_to.
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
                changes={k: {"before": before[k], "after": updates[k]} for k in updates},
            )
        if payload.resource is not None:
            self.repo.upsert_resource(
                subtask_id=row.id, project_id=row.project_id,
                **payload.resource.model_dump(exclude_unset=True),
            )
        self.db.commit()
        return row

    def delete(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(subtask_id)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="subtask", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, subtask_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(subtask_id)
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="subtask", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def replace_dependencies(self, subtask_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row = self.get_by_id(subtask_id)
        self._guard_dependency_cycle(subtask_id, depends_on_ids)
        self.repo.replace_dependencies(subtask_id, depends_on_ids)
        self.audit.write(
            project_id=row.project_id,
            target_kind="subtask", target_id=subtask_id,
            action="update", actor_user_id=caller_user_id,
            changes={"depends_on": depends_on_ids},
        )
        self.db.commit()
        return row, depends_on_ids

    def _guard_dependency_cycle(self, subtask_id: str, depends_on_ids: List[str]) -> None:
        if subtask_id in depends_on_ids:
            raise DependencyCycleError("A subtask cannot depend on itself")
        visited: set[str] = set()
        frontier = list(depends_on_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == subtask_id:
                raise DependencyCycleError("Proposed dependencies form a cycle")
            frontier.extend(self.repo.list_dependencies_for(current))

    def _validate_assignee(self, assignee_user_id: str, project_id: str) -> None:
        """Round-7 Q9: same as TaskService._validate_assignee — see that
        docstring for the 4 invariants checked."""
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
