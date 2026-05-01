"""Milestone repository."""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models.milestone import MilestoneModel
from ..models.activity import ActivityModel
from ..models.activity_resource import ActivityResourceModel
from ..models.task import TaskModel
from ..models.task_resource import TaskResourceModel
from ..models.subtask import SubtaskModel
from ..models.subtask_resource import SubtaskResourceModel
from ....domain.milestones.milestone import Milestone


class MilestoneRepository:
    """Data access for milestones."""

    def __init__(self, db: Session):
        self.db = db

    def _to_domain(self, m: MilestoneModel, *, with_vendors: bool = True) -> Milestone:
        dom = Milestone(
            id=m.id,
            project_id=m.project_id,
            name=m.name,
            description=m.description,
            start_date=m.start_date,
            end_date=m.end_date,
            position=m.position,
            created_at=m.created_at,
            updated_at=m.updated_at,
            created_by=m.created_by,
            updated_by=m.updated_by,
            deleted_at=m.deleted_at,
            status=getattr(m, "status", None) or "not_completed",
            depends=getattr(m, "depends", None),
        )
        if with_vendors:
            from .vendor_repository import VendorRepository
            dom.vendors = VendorRepository(self.db).list_milestone_vendors(m.id)
        return dom

    # ---------- reads ----------

    def get_by_id(self, milestone_id: str, include_deleted: bool = False) -> Optional[Milestone]:
        q = self.db.query(MilestoneModel).filter(MilestoneModel.id == milestone_id)
        if not include_deleted:
            q = q.filter(MilestoneModel.deleted_at.is_(None))
        row = q.first()
        return self._to_domain(row) if row else None

    def get_model(self, milestone_id: str, include_deleted: bool = False) -> Optional[MilestoneModel]:
        q = self.db.query(MilestoneModel).filter(MilestoneModel.id == milestone_id)
        if not include_deleted:
            q = q.filter(MilestoneModel.deleted_at.is_(None))
        return q.first()

    def list_by_project(
        self,
        project_id: str,
        offset: int = 0,
        limit: int = 20,
        include_deleted: bool = False,
    ) -> Tuple[List[Milestone], int]:
        base = self.db.query(MilestoneModel).filter(MilestoneModel.project_id == project_id)
        if not include_deleted:
            base = base.filter(MilestoneModel.deleted_at.is_(None))
        total = base.with_entities(func.count(MilestoneModel.id)).scalar() or 0
        rows = (
            base.order_by(MilestoneModel.position.asc(), MilestoneModel.id.asc())
            .offset(offset).limit(limit).all()
        )
        return [self._to_domain(r) for r in rows], total

    def next_position(self, project_id: str) -> int:
        cur = (
            self.db.query(func.max(MilestoneModel.position))
            .filter(MilestoneModel.project_id == project_id)
            .filter(MilestoneModel.deleted_at.is_(None))
            .scalar()
        )
        return (cur or 0) + 1

    # ---------- writes ----------

    def create(
        self, *,
        project_id: str, name: str, description: Optional[str],
        start_date: datetime, end_date: datetime,
        position: int,
        created_by: Optional[int],
        status: str = "not_completed",
        depends: Optional[list] = None,
    ) -> Milestone:
        m = MilestoneModel(
            project_id=project_id,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            position=position,
            created_by=created_by,
            updated_by=created_by,
            status=status,
            depends=depends,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return self._to_domain(m, with_vendors=False)

    def update(
        self, milestone_id: str, *, updates: dict, updated_by: Optional[int],
    ) -> Milestone:
        m = self.get_model(milestone_id)
        if m is None:
            raise LookupError(f"Milestone {milestone_id} not found")
        for k, v in updates.items():
            setattr(m, k, v)
        m.updated_by = updated_by
        self.db.commit()
        self.db.refresh(m)
        return self._to_domain(m)

    # ---------- soft delete + cascade ----------

    def soft_delete_with_cascade(self, milestone_id: str, deleted_by: Optional[int]) -> None:
        """
        Soft-delete a milestone and every descendant (activities, their
        resources, tasks, their resources, subtasks, their resources).
        One transaction.
        """
        now = datetime.now(timezone.utc)

        # Collect the ids of descendants via subqueries keyed on the
        # milestone being deleted. All live rows under the milestone are
        # stamped; already-soft-deleted rows are left alone.
        activity_ids = select(ActivityModel.id).where(
            ActivityModel.milestone_id == milestone_id,
            ActivityModel.deleted_at.is_(None),
        )
        task_ids = select(TaskModel.id).where(
            TaskModel.activity_id.in_(activity_ids),
            TaskModel.deleted_at.is_(None),
        )
        subtask_ids = select(SubtaskModel.id).where(
            SubtaskModel.task_id.in_(task_ids),
            SubtaskModel.deleted_at.is_(None),
        )

        # Resource rows first (leaves of the dependency chain)
        self.db.execute(
            update(SubtaskResourceModel)
            .where(
                SubtaskResourceModel.subtask_id.in_(subtask_ids),
                SubtaskResourceModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )
        self.db.execute(
            update(TaskResourceModel)
            .where(
                TaskResourceModel.task_id.in_(task_ids),
                TaskResourceModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )
        self.db.execute(
            update(ActivityResourceModel)
            .where(
                ActivityResourceModel.activity_id.in_(activity_ids),
                ActivityResourceModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )
        # Then the main entities, bottom-up
        self.db.execute(
            update(SubtaskModel)
            .where(
                SubtaskModel.task_id.in_(task_ids),
                SubtaskModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now, updated_by=deleted_by)
        )
        self.db.execute(
            update(TaskModel)
            .where(
                TaskModel.activity_id.in_(activity_ids),
                TaskModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now, updated_by=deleted_by)
        )
        self.db.execute(
            update(ActivityModel)
            .where(
                ActivityModel.milestone_id == milestone_id,
                ActivityModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now, updated_by=deleted_by)
        )
        self.db.execute(
            update(MilestoneModel)
            .where(
                MilestoneModel.id == milestone_id,
                MilestoneModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now, updated_by=deleted_by)
        )
        self.db.commit()

    def restore(self, milestone_id: str, restored_by: Optional[int]) -> Milestone:
        """
        Restore a single milestone row. Does NOT auto-restore descendants --
        the caller can restore them independently if desired. Soft-deleted
        descendants stay soft-deleted (audit-preserving).
        """
        m = self.get_model(milestone_id, include_deleted=True)
        if m is None:
            raise LookupError(f"Milestone {milestone_id} not found")
        if m.deleted_at is None:
            return self._to_domain(m)  # already live; no-op
        m.deleted_at = None
        m.updated_at = datetime.now(timezone.utc)
        m.updated_by = restored_by
        self.db.commit()
        self.db.refresh(m)
        return self._to_domain(m)
