"""ActivityService — CRUD + resource sidecar upsert + dependency cycle guard."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.errors import (
    ActivityNotFoundError,
    DependencyCycleError,
    MilestoneNotFoundError,
)
from app.repositories.activity_repository import ActivityRepository
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.schemas.activity import ActivityCreateRequest, ActivityUpdateRequest


class ActivityService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ActivityRepository(db)
        self.milestones = MilestoneRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    def get_by_id(self, activity_id: str):
        row = self.repo.get_by_id(activity_id)
        if row is None:
            raise ActivityNotFoundError(f"Activity {activity_id!r} not found")
        return row

    def list_for_milestone(self, milestone_id: str, *, offset=1, page_size=50, include_deleted=False):
        return self.repo.list_for_milestone(
            milestone_id, offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    def create(self, payload: ActivityCreateRequest, *, caller_user_id: Optional[str]):
        milestone = self.milestones.get_by_id(payload.milestone_id)
        if milestone is None:
            raise MilestoneNotFoundError(f"Milestone {payload.milestone_id!r} not found")
        position = self.repo.next_position_for_milestone(payload.milestone_id)
        row = self.repo.create(
            project_id=milestone.project_id,
            milestone_id=payload.milestone_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            priority=payload.priority,
            owner_division=payload.owner_division,
            concerned_divisions=payload.concerned_divisions,
            vendor_id=payload.vendor_id,
            position=position,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if payload.depends_on:
            self._guard_dependency_cycle(row.id, payload.depends_on)
            self.repo.replace_dependencies(row.id, payload.depends_on)
        if payload.resource is not None:
            self.repo.upsert_resource(
                activity_id=row.id, project_id=row.project_id,
                **payload.resource.model_dump(exclude_unset=True),
            )
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "milestone_id": row.milestone_id},
        )
        self.db.commit()
        return row

    def update(self, activity_id: str, payload: ActivityUpdateRequest, *, caller_user_id: Optional[str], request=None):
        row = self.get_by_id(activity_id)
        updates = payload.model_dump(exclude_unset=True, exclude={"resource"})
        # Field-level RBAC: touched-fields includes "resource" iff the sidecar
        # is being written.
        touched = set(updates.keys())
        if payload.resource is not None:
            touched.add("resource")
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
                changes={k: {"before": before[k], "after": updates[k]} for k in updates},
            )
        if payload.resource is not None:
            self.repo.upsert_resource(
                activity_id=row.id, project_id=row.project_id,
                **payload.resource.model_dump(exclude_unset=True),
            )
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
        row = self.get_by_id(activity_id)
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def replace_dependencies(self, activity_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row = self.get_by_id(activity_id)
        self._guard_dependency_cycle(activity_id, depends_on_ids)
        self.repo.replace_dependencies(activity_id, depends_on_ids)
        self.audit.write(
            project_id=row.project_id,
            target_kind="activity", target_id=activity_id,
            action="update", actor_user_id=caller_user_id,
            changes={"depends_on": depends_on_ids},
        )
        self.db.commit()
        return row, depends_on_ids

    def _guard_dependency_cycle(self, activity_id: str, depends_on_ids: List[str]) -> None:
        if activity_id in depends_on_ids:
            raise DependencyCycleError("An activity cannot depend on itself")
        visited: set[str] = set()
        frontier = list(depends_on_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == activity_id:
                raise DependencyCycleError("Proposed dependencies form a cycle")
            frontier.extend(self.repo.list_dependencies_for(current))
