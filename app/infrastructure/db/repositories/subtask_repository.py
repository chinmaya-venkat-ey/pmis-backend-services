"""Subtask repository (with resource sub-entity ops)."""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ..models.subtask import SubtaskModel
from ..models.subtask_resource import SubtaskResourceModel
from ....domain.subtasks.subtask import Subtask
from ....domain.subtasks.subtask_resource import SubtaskResource


class SubtaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, s: SubtaskModel) -> Subtask:
        return Subtask(
            id=s.id,
            project_id=s.project_id,
            task_id=s.task_id,
            name=s.name,
            description=s.description,
            type=s.type,
            start_date=s.start_date,
            end_date=s.end_date,
            actual_start_date=s.actual_start_date,
            actual_end_date=s.actual_end_date,
            position=s.position,
            resource_mode=s.resource_mode,
            resource_count=s.resource_count,
            created_at=s.created_at,
            updated_at=s.updated_at,
            created_by=s.created_by,
            updated_by=s.updated_by,
            deleted_at=s.deleted_at,
        )

    def _resource_to_domain(self, r: SubtaskResourceModel) -> SubtaskResource:
        return SubtaskResource(
            id=r.id,
            subtask_id=r.subtask_id,
            project_id=r.project_id,
            resource_name=r.resource_name,
            onboard_date=r.onboard_date,
            actual_onboard_date=r.actual_onboard_date,
            offboard_date=r.offboard_date,
            actual_offboard_date=r.actual_offboard_date,
            position=r.position,
            designation=r.designation,
            job_role=r.job_role,
            qualification=r.qualification,
            experience_years=r.experience_years,
            created_at=r.created_at,
            updated_at=r.updated_at,
            deleted_at=r.deleted_at,
        )

    # ---------- reads ----------

    def get_by_id(self, subtask_id: str, include_deleted: bool = False) -> Optional[Subtask]:
        q = self.db.query(SubtaskModel).filter(SubtaskModel.id == subtask_id)
        if not include_deleted:
            q = q.filter(SubtaskModel.deleted_at.is_(None))
        row = q.first()
        return self._to_domain(row) if row else None

    def get_model(self, subtask_id: str, include_deleted: bool = False) -> Optional[SubtaskModel]:
        q = self.db.query(SubtaskModel).filter(SubtaskModel.id == subtask_id)
        if not include_deleted:
            q = q.filter(SubtaskModel.deleted_at.is_(None))
        return q.first()

    def list_by_task(
        self, task_id: str, offset: int = 0, limit: int = 20,
        include_deleted: bool = False,
    ) -> Tuple[List[Subtask], int]:
        base = self.db.query(SubtaskModel).filter(SubtaskModel.task_id == task_id)
        if not include_deleted:
            base = base.filter(SubtaskModel.deleted_at.is_(None))
        total = base.with_entities(func.count(SubtaskModel.id)).scalar() or 0
        rows = (
            base.order_by(SubtaskModel.position.asc(), SubtaskModel.id.asc())
            .offset(offset).limit(limit).all()
        )
        return [self._to_domain(r) for r in rows], total

    def next_position(self, task_id: str) -> int:
        cur = (
            self.db.query(func.max(SubtaskModel.position))
            .filter(SubtaskModel.task_id == task_id)
            .filter(SubtaskModel.deleted_at.is_(None))
            .scalar()
        )
        return (cur or 0) + 1

    def get_live_resource(self, subtask_id: str) -> Optional[SubtaskResource]:
        row = (
            self.db.query(SubtaskResourceModel)
            .filter(SubtaskResourceModel.subtask_id == subtask_id)
            .filter(SubtaskResourceModel.deleted_at.is_(None))
            .first()
        )
        return self._resource_to_domain(row) if row else None

    # ---------- writes ----------

    def create(
        self, *,
        project_id: str, task_id: str, name: str, description: Optional[str],
        type: str, start_date: datetime, end_date: datetime,
        actual_start_date: Optional[datetime], actual_end_date: Optional[datetime],
        position: int, created_by: Optional[int],
        resource_mode: Optional[str] = None,
        resource_count: Optional[int] = None,
    ) -> Subtask:
        s = SubtaskModel(
            project_id=project_id,
            task_id=task_id,
            name=name,
            description=description,
            type=type,
            start_date=start_date,
            end_date=end_date,
            actual_start_date=actual_start_date,
            actual_end_date=actual_end_date,
            position=position,
            resource_mode=resource_mode,
            resource_count=resource_count,
            created_by=created_by,
            updated_by=created_by,
        )
        self.db.add(s)
        self.db.flush()
        return self._to_domain(s)

    def update(self, subtask_id: str, *, updates: dict, updated_by: Optional[int]) -> Subtask:
        s = self.get_model(subtask_id)
        if s is None:
            raise LookupError(f"Subtask {subtask_id} not found")
        for k, v in updates.items():
            setattr(s, k, v)
        s.updated_by = updated_by
        self.db.flush()
        return self._to_domain(s)

    # ---------- resource sub-entity ----------

    def insert_resource(self, *, subtask_id: str, project_id: str, data: dict) -> SubtaskResource:
        r = SubtaskResourceModel(
            subtask_id=subtask_id,
            project_id=project_id,
            resource_name=data["resource_name"],
            onboard_date=data.get("onboard_date"),
            actual_onboard_date=data.get("actual_onboard_date"),
            offboard_date=data.get("offboard_date"),
            actual_offboard_date=data.get("actual_offboard_date"),
            position=data.get("position"),
            designation=data.get("designation"),
            job_role=data.get("job_role"),
            qualification=data.get("qualification"),
            experience_years=data.get("experience_years"),
        )
        self.db.add(r)
        self.db.flush()
        return self._resource_to_domain(r)

    def upsert_resource(self, *, subtask_id: str, project_id: str, data: dict) -> SubtaskResource:
        existing = (
            self.db.query(SubtaskResourceModel)
            .filter(
                SubtaskResourceModel.subtask_id == subtask_id,
                SubtaskResourceModel.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            return self.insert_resource(subtask_id=subtask_id, project_id=project_id, data=data)
        for field in (
            "resource_name", "onboard_date", "actual_onboard_date",
            "offboard_date", "actual_offboard_date",
            "position", "designation", "job_role", "qualification", "experience_years",
        ):
            if field in data:
                setattr(existing, field, data[field])
        existing.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return self._resource_to_domain(existing)

    def soft_delete_live_resource(self, subtask_id: str) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(
            update(SubtaskResourceModel)
            .where(
                SubtaskResourceModel.subtask_id == subtask_id,
                SubtaskResourceModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )

    # ---------- delete (subtask is a leaf) ----------

    def soft_delete(self, subtask_id: str, deleted_by: Optional[int]) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(update(SubtaskResourceModel).where(
            SubtaskResourceModel.subtask_id == subtask_id,
            SubtaskResourceModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now))
        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.id == subtask_id,
            SubtaskModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now, updated_by=deleted_by))
        self.db.commit()

    def restore(self, subtask_id: str, restored_by: Optional[int]) -> Subtask:
        s = self.get_model(subtask_id, include_deleted=True)
        if s is None:
            raise LookupError(f"Subtask {subtask_id} not found")
        if s.deleted_at is None:
            return self._to_domain(s)
        s.deleted_at = None
        s.updated_at = datetime.now(timezone.utc)
        s.updated_by = restored_by
        self.db.commit()
        self.db.refresh(s)
        return self._to_domain(s)
