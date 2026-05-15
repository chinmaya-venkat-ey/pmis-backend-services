"""MilestoneService — CRUD + position management + dependency cycle guard."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.errors import (
    DependencyCycleError,
    MilestoneNotFoundError,
    ProjectNotFoundError,
)
from app.repositories.milestone_repository import MilestoneRepository
from app.repositories.project_audit_log_repository import ProjectAuditLogRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.milestone import MilestoneCreateRequest, MilestoneUpdateRequest


class MilestoneService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MilestoneRepository(db)
        self.projects = ProjectRepository(db)
        self.audit = ProjectAuditLogRepository(db)

    # ------------------------------------------------------------------ read

    def get_by_id(self, milestone_id: str):
        row = self.repo.get_by_id(milestone_id)
        if row is None:
            raise MilestoneNotFoundError(f"Milestone {milestone_id!r} not found")
        return row

    def list_for_project(
        self, project_id: str, *,
        offset: int = 1, page_size: int = 50, include_deleted: bool = False,
    ):
        return self.repo.list_for_project(
            project_id,
            offset=offset, page_size=page_size, include_deleted=include_deleted,
        )

    # ------------------------------------------------------------------ write

    def create(
        self,
        project_id: str,
        payload: MilestoneCreateRequest,
        *, caller_user_id: Optional[str],
    ):
        if self.projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(f"Project {project_id!r} not found")
        position = self.repo.next_position_for_project(project_id)
        row = self.repo.create(
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            start_date=payload.start_date,
            end_date=payload.end_date,
            priority=payload.priority,
            position=position,
            created_by=caller_user_id,
            updated_by=caller_user_id,
        )
        if payload.depends_on:
            self._guard_dependency_cycle(row.id, payload.depends_on)
            self.repo.replace_dependencies(row.id, payload.depends_on)
        if payload.vendor_ids:
            self.repo.set_vendor_mapping(row.id, payload.vendor_ids)
        self.audit.write(
            project_id=project_id,
            target_kind="milestone", target_id=row.id,
            action="create", actor_user_id=caller_user_id,
            changes={"name": row.name, "position": row.position},
        )
        self.db.commit()
        return row

    def update(self, milestone_id: str, payload: MilestoneUpdateRequest, *, caller_user_id: Optional[str], request=None):
        row = self.get_by_id(milestone_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return row
        if request is not None:
            from app.core.permissions import MILESTONE_FIELD_CODES
            from app.core.rbac import assert_field_writes_allowed

            assert_field_writes_allowed(
                request,
                field_codes=MILESTONE_FIELD_CODES,
                touched_fields=set(updates.keys()),
                scope_key=("project", row.project_id),
            )
        before = {k: getattr(row, k) for k in updates}
        self.repo.update(row, updated_by=caller_user_id, **updates)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="update", actor_user_id=caller_user_id,
            changes={k: {"before": before[k], "after": updates[k]} for k in updates},
        )
        self.db.commit()
        return row

    def delete(self, milestone_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(milestone_id)
        self.repo.soft_delete(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="delete", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    def restore(self, milestone_id: str, *, caller_user_id: Optional[str]):
        row = self.get_by_id(milestone_id)
        self.repo.restore(row)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=row.id,
            action="restore", actor_user_id=caller_user_id,
        )
        self.db.commit()
        return row

    # ------------------------------------------------------------------ dependencies

    def replace_dependencies(self, milestone_id: str, depends_on_ids: List[str], *, caller_user_id: Optional[str]):
        row = self.get_by_id(milestone_id)
        self._guard_dependency_cycle(milestone_id, depends_on_ids)
        self.repo.replace_dependencies(milestone_id, depends_on_ids)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=milestone_id,
            action="update", actor_user_id=caller_user_id,
            changes={"depends_on": depends_on_ids},
        )
        self.db.commit()
        return row, depends_on_ids

    def _guard_dependency_cycle(self, milestone_id: str, depends_on_ids: List[str]) -> None:
        """Reject if any of the proposed dependencies (directly or transitively)
        depend back on milestone_id."""
        if milestone_id in depends_on_ids:
            raise DependencyCycleError(
                "A milestone cannot depend on itself",
                details={"milestone_id": milestone_id},
            )
        visited: set[str] = set()
        frontier = list(depends_on_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == milestone_id:
                raise DependencyCycleError(
                    "Proposed dependencies form a cycle",
                    details={"milestone_id": milestone_id, "depends_on": depends_on_ids},
                )
            frontier.extend(self.repo.list_dependencies_for(current))

    # ------------------------------------------------------------------ vendors

    def set_vendors(self, milestone_id: str, vendor_ids: List[str], *, caller_user_id: Optional[str]):
        row = self.get_by_id(milestone_id)
        self.repo.set_vendor_mapping(milestone_id, vendor_ids)
        self.audit.write(
            project_id=row.project_id,
            target_kind="milestone", target_id=milestone_id,
            action="update", actor_user_id=caller_user_id,
            changes={"vendor_ids": vendor_ids},
        )
        self.db.commit()
        return row, vendor_ids
