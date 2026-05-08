"""Task repository (with resource sub-entity ops)."""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models.task import TaskModel
from ..models.task_resource import TaskResourceModel
from ..models.subtask import SubtaskModel
from ..models.subtask_resource import SubtaskResourceModel
from ....domain.tasks.task import Task
from ....domain.tasks.task_resource import TaskResource
from ....shared.comments_attachments_cascade import (
    cascade_restore_comments_and_attachments,
    cascade_soft_delete_comments_and_attachments,
)


class TaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, t: TaskModel) -> Task:
        return Task(
            id=t.id,
            project_id=t.project_id,
            activity_id=t.activity_id,
            name=t.name,
            description=t.description,
            type=t.type,
            start_date=t.start_date,
            end_date=t.end_date,
            actual_start_date=t.actual_start_date,
            actual_end_date=t.actual_end_date,
            position=t.position,
            resource_mode=t.resource_mode,
            resource_count=t.resource_count,
            status=getattr(t, "status", None),
            assigned_to=getattr(t, "assigned_to", None),
            created_at=t.created_at,
            updated_at=t.updated_at,
            created_by=t.created_by,
            updated_by=t.updated_by,
            deleted_at=t.deleted_at,
        )

    def _resource_to_domain(self, r: TaskResourceModel) -> TaskResource:
        return TaskResource(
            id=r.id,
            task_id=r.task_id,
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

    def get_by_id(self, task_id: str, include_deleted: bool = False) -> Optional[Task]:
        q = self.db.query(TaskModel).filter(TaskModel.id == task_id)
        if not include_deleted:
            q = q.filter(TaskModel.deleted_at.is_(None))
        row = q.first()
        return self._to_domain(row) if row else None

    def get_model(self, task_id: str, include_deleted: bool = False) -> Optional[TaskModel]:
        q = self.db.query(TaskModel).filter(TaskModel.id == task_id)
        if not include_deleted:
            q = q.filter(TaskModel.deleted_at.is_(None))
        return q.first()

    def list_by_activity(
        self, activity_id: str, offset: int = 0, limit: int = 20,
        include_deleted: bool = False,
    ) -> Tuple[List[Task], int]:
        base = self.db.query(TaskModel).filter(TaskModel.activity_id == activity_id)
        if not include_deleted:
            base = base.filter(TaskModel.deleted_at.is_(None))
        total = base.with_entities(func.count(TaskModel.id)).scalar() or 0
        rows = (
            base.order_by(TaskModel.position.asc(), TaskModel.id.asc())
            .offset(offset).limit(limit).all()
        )
        return [self._to_domain(r) for r in rows], total

    def next_position(self, activity_id: str) -> int:
        cur = (
            self.db.query(func.max(TaskModel.position))
            .filter(TaskModel.activity_id == activity_id)
            .filter(TaskModel.deleted_at.is_(None))
            .scalar()
        )
        return (cur or 0) + 1

    def position_taken(self, activity_id: str, position: int) -> bool:
        """True iff a live task in ``activity_id`` already occupies
        ``position``. Lets the create service auto-bump caller-supplied
        positions that would otherwise trip the unique index — see
        ``MilestoneRepository.position_taken`` for the rationale.
        """
        return self.db.query(TaskModel.id).filter(
            TaskModel.activity_id == activity_id,
            TaskModel.position == position,
            TaskModel.deleted_at.is_(None),
        ).first() is not None

    def get_live_resource(self, task_id: str) -> Optional[TaskResource]:
        row = (
            self.db.query(TaskResourceModel)
            .filter(TaskResourceModel.task_id == task_id)
            .filter(TaskResourceModel.deleted_at.is_(None))
            .first()
        )
        return self._resource_to_domain(row) if row else None

    # ---------- writes ----------

    def create(
        self, *,
        project_id: str, activity_id: str, name: str, description: Optional[str],
        type: str, start_date: datetime, end_date: datetime,
        actual_start_date: Optional[datetime], actual_end_date: Optional[datetime],
        position: int, created_by: Optional[str],
        resource_mode: Optional[str] = None,
        resource_count: Optional[int] = None,
        status: Optional[str] = None,
        # Doc 41 follow-up: optional assignee user UUID.
        assigned_to: Optional[str] = None,
    ) -> Task:
        t = TaskModel(
            project_id=project_id,
            activity_id=activity_id,
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
            status=status,
            assigned_to=assigned_to,
            created_by=created_by,
            updated_by=created_by,
        )
        self.db.add(t)
        self.db.flush()
        return self._to_domain(t)

    def update(self, task_id: str, *, updates: dict, updated_by: Optional[str]) -> Task:
        t = self.get_model(task_id)
        if t is None:
            raise LookupError(f"Task {task_id} not found")
        for k, v in updates.items():
            setattr(t, k, v)
        t.updated_by = updated_by
        self.db.flush()
        return self._to_domain(t)

    # ---------- resource sub-entity ----------

    def insert_resource(self, *, task_id: str, project_id: str, data: dict) -> TaskResource:
        r = TaskResourceModel(
            task_id=task_id,
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

    def upsert_resource(self, *, task_id: str, project_id: str, data: dict) -> TaskResource:
        existing = (
            self.db.query(TaskResourceModel)
            .filter(
                TaskResourceModel.task_id == task_id,
                TaskResourceModel.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            return self.insert_resource(task_id=task_id, project_id=project_id, data=data)
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

    def soft_delete_live_resource(self, task_id: str) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(
            update(TaskResourceModel)
            .where(
                TaskResourceModel.task_id == task_id,
                TaskResourceModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )

    # ---------- delete + cascade (task subtree) ----------

    def soft_delete_with_cascade(self, task_id: str, deleted_by: Optional[str]) -> None:
        now = datetime.now(timezone.utc)
        subtask_ids = select(SubtaskModel.id).where(
            SubtaskModel.task_id == task_id,
            SubtaskModel.deleted_at.is_(None),
        )
        self.db.execute(update(SubtaskResourceModel).where(
            SubtaskResourceModel.subtask_id.in_(subtask_ids),
            SubtaskResourceModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now))
        self.db.execute(update(TaskResourceModel).where(
            TaskResourceModel.task_id == task_id,
            TaskResourceModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now))
        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.task_id == task_id,
            SubtaskModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now, updated_by=deleted_by))
        self.db.execute(update(TaskModel).where(
            TaskModel.id == task_id,
            TaskModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now, updated_by=deleted_by))

        # Doc 34: cascade comments + attachments under the task subtree.
        cascade_soft_delete_comments_and_attachments(
            self.db,
            targets=[
                ("task", task_id),
                ("subtask", select(SubtaskModel.id).where(
                    SubtaskModel.task_id == task_id,
                    SubtaskModel.deleted_at == now,
                )),
            ],
            deleted_by=deleted_by,
            now=now,
        )

        self.db.commit()

    def restore(self, task_id: str, restored_by: Optional[int]) -> Task:
        """
        Restore the task + every S/resource/comment/attachment that was
        soft-deleted as part of the same cascade event (doc 34). Dep
        edges are NOT auto-restored.
        """
        t = self.get_model(task_id, include_deleted=True)
        if t is None:
            raise LookupError(f"Task {task_id} not found")
        if t.deleted_at is None:
            return self._to_domain(t)

        cascade_ts = t.deleted_at
        now = datetime.now(timezone.utc)

        t.deleted_at = None
        t.updated_at = now
        t.updated_by = restored_by
        self.db.flush()

        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.task_id == task_id,
            SubtaskModel.deleted_at == cascade_ts,
        ).values(deleted_at=None, updated_at=now, updated_by=restored_by))
        self.db.execute(update(TaskResourceModel).where(
            TaskResourceModel.task_id == task_id,
            TaskResourceModel.deleted_at == cascade_ts,
        ).values(deleted_at=None, updated_at=now))
        self.db.execute(update(SubtaskResourceModel).where(
            SubtaskResourceModel.deleted_at == cascade_ts,
            SubtaskResourceModel.subtask_id.in_(
                select(SubtaskModel.id).where(
                    SubtaskModel.task_id == task_id,
                    SubtaskModel.deleted_at.is_(None),
                )
            ),
        ).values(deleted_at=None, updated_at=now))

        cascade_restore_comments_and_attachments(
            self.db,
            targets=[
                ("task", task_id),
                ("subtask", select(SubtaskModel.id).where(
                    SubtaskModel.task_id == task_id,
                    SubtaskModel.deleted_at.is_(None),
                )),
            ],
            cascade_deleted_at=cascade_ts,
        )

        self.db.commit()
        self.db.refresh(t)
        return self._to_domain(t)
