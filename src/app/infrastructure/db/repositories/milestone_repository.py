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
from ....shared.comments_attachments_cascade import (
    cascade_restore_comments_and_attachments,
    cascade_soft_delete_comments_and_attachments,
)


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
        )
        # Live milestone-dependency target ids (sorted) come from the
        # milestone_dependencies edge table. Local import to avoid cycles.
        from .dependency_repository import DependencyRepository
        dom.depends_on = DependencyRepository(self.db).list_milestone_dependencies(m.id)
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

    def position_taken(self, project_id: str, position: int) -> bool:
        """True iff a live milestone in ``project_id`` already occupies
        ``position``. Used by the create service to detect a caller-supplied
        ``position`` that would collide with the
        ``uq_milestones_project_position_live`` unique index, so the
        request can be transparently bumped to ``next_position`` instead
        of crashing the INSERT with an IntegrityError → 500.

        Swagger UI auto-fills the ``position`` field with ``0`` when the
        caller doesn't override it; without this guard, the second
        milestone created from Swagger always trips the unique index.
        """
        return self.db.query(MilestoneModel.id).filter(
            MilestoneModel.project_id == project_id,
            MilestoneModel.position == position,
            MilestoneModel.deleted_at.is_(None),
        ).first() is not None

    # ---------- writes ----------

    def create(
        self, *,
        project_id: str, name: str, description: Optional[str],
        start_date: datetime, end_date: datetime,
        position: int,
        created_by: Optional[str],
        status: str = "not_completed",
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
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return self._to_domain(m, with_vendors=False)

    def update(
        self, milestone_id: str, *, updates: dict, updated_by: Optional[str],
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

    def soft_delete_with_cascade(self, milestone_id: str, deleted_by: Optional[str]) -> None:
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

        # Doc 34: cascade comments + attachments under every (kind, id)
        # we just soft-deleted. The subqueries used above are reused
        # here so the OR predicate matches the same subtree exactly.
        # Same ``now`` timestamp lets the matching restore-cascade
        # identify these rows as "deleted with this milestone".
        cascade_soft_delete_comments_and_attachments(
            self.db,
            targets=[
                ("milestone", milestone_id),
                ("activity", select(ActivityModel.id).where(
                    ActivityModel.milestone_id == milestone_id,
                    ActivityModel.deleted_at == now,
                )),
                ("task", select(TaskModel.id).where(
                    TaskModel.deleted_at == now,
                    TaskModel.activity_id.in_(
                        select(ActivityModel.id).where(
                            ActivityModel.milestone_id == milestone_id,
                            ActivityModel.deleted_at == now,
                        )
                    ),
                )),
                ("subtask", select(SubtaskModel.id).where(
                    SubtaskModel.deleted_at == now,
                    SubtaskModel.task_id.in_(
                        select(TaskModel.id).where(
                            TaskModel.deleted_at == now,
                            TaskModel.activity_id.in_(
                                select(ActivityModel.id).where(
                                    ActivityModel.milestone_id == milestone_id,
                                    ActivityModel.deleted_at == now,
                                )
                            ),
                        )
                    ),
                )),
            ],
            deleted_by=deleted_by,
            now=now,
        )

        self.db.commit()

    def restore(self, milestone_id: str, restored_by: Optional[int]) -> Milestone:
        """
        Restore a milestone PLUS every A/T/S/resource/comment/attachment
        that was soft-deleted as part of the same cascade event (doc 34).

        Identification: the soft-delete cascade stamps every row in the
        subtree with the milestone's exact ``deleted_at`` timestamp.
        Restoring that timestamp's worth of rows brings back exactly
        what came down with the milestone — no more (rows soft-deleted
        independently before the parent went down keep their
        timestamps and stay dead) and no less.

        Dep edges are NOT auto-restored. They were soft-deleted as a
        side effect of the entity going away; bringing the entity back
        doesn't necessarily mean the user wants the old dependencies
        back (the target may have been gone for a long time, dates may
        have shifted, etc.). Re-establish via PATCH dependsOn explicitly.
        """
        m = self.get_model(milestone_id, include_deleted=True)
        if m is None:
            raise LookupError(f"Milestone {milestone_id} not found")
        if m.deleted_at is None:
            return self._to_domain(m)  # already live; no-op

        cascade_ts = m.deleted_at
        now = datetime.now(timezone.utc)

        # Restore the milestone row first.
        m.deleted_at = None
        m.updated_at = now
        m.updated_by = restored_by
        self.db.flush()

        # Restore every A/T/S/resource row whose deleted_at exactly
        # matches the cascade timestamp. Top-down order (M is already
        # done) — A then T then S then their resources.
        self.db.execute(update(ActivityModel).where(
            ActivityModel.milestone_id == milestone_id,
            ActivityModel.deleted_at == cascade_ts,
        ).values(deleted_at=None, updated_at=now, updated_by=restored_by))
        self.db.execute(update(TaskModel).where(
            TaskModel.project_id == m.project_id,
            TaskModel.deleted_at == cascade_ts,
            TaskModel.activity_id.in_(
                select(ActivityModel.id).where(
                    ActivityModel.milestone_id == milestone_id,
                    ActivityModel.deleted_at.is_(None),
                )
            ),
        ).values(deleted_at=None, updated_at=now, updated_by=restored_by))
        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.project_id == m.project_id,
            SubtaskModel.deleted_at == cascade_ts,
            SubtaskModel.task_id.in_(
                select(TaskModel.id).where(
                    TaskModel.deleted_at.is_(None),
                    TaskModel.activity_id.in_(
                        select(ActivityModel.id).where(
                            ActivityModel.milestone_id == milestone_id,
                            ActivityModel.deleted_at.is_(None),
                        )
                    ),
                )
            ),
        ).values(deleted_at=None, updated_at=now, updated_by=restored_by))

        # Resource rows hang off the matching M/A/T/S (now revived).
        self.db.execute(update(ActivityResourceModel).where(
            ActivityResourceModel.deleted_at == cascade_ts,
            ActivityResourceModel.activity_id.in_(
                select(ActivityModel.id).where(
                    ActivityModel.milestone_id == milestone_id,
                    ActivityModel.deleted_at.is_(None),
                )
            ),
        ).values(deleted_at=None, updated_at=now))
        self.db.execute(update(TaskResourceModel).where(
            TaskResourceModel.deleted_at == cascade_ts,
            TaskResourceModel.task_id.in_(
                select(TaskModel.id).where(
                    TaskModel.deleted_at.is_(None),
                    TaskModel.activity_id.in_(
                        select(ActivityModel.id).where(
                            ActivityModel.milestone_id == milestone_id,
                            ActivityModel.deleted_at.is_(None),
                        )
                    ),
                )
            ),
        ).values(deleted_at=None, updated_at=now))
        self.db.execute(update(SubtaskResourceModel).where(
            SubtaskResourceModel.deleted_at == cascade_ts,
            SubtaskResourceModel.subtask_id.in_(
                select(SubtaskModel.id).where(
                    SubtaskModel.deleted_at.is_(None),
                    SubtaskModel.task_id.in_(
                        select(TaskModel.id).where(
                            TaskModel.deleted_at.is_(None),
                            TaskModel.activity_id.in_(
                                select(ActivityModel.id).where(
                                    ActivityModel.milestone_id == milestone_id,
                                    ActivityModel.deleted_at.is_(None),
                                )
                            ),
                        )
                    ),
                )
            ),
        ).values(deleted_at=None, updated_at=now))

        # Comments + attachments — match the cascade-deleted set.
        cascade_restore_comments_and_attachments(
            self.db,
            targets=[
                ("milestone", milestone_id),
                ("activity", select(ActivityModel.id).where(
                    ActivityModel.milestone_id == milestone_id,
                    ActivityModel.deleted_at.is_(None),
                )),
                ("task", select(TaskModel.id).where(
                    TaskModel.deleted_at.is_(None),
                    TaskModel.activity_id.in_(
                        select(ActivityModel.id).where(
                            ActivityModel.milestone_id == milestone_id,
                            ActivityModel.deleted_at.is_(None),
                        )
                    ),
                )),
                ("subtask", select(SubtaskModel.id).where(
                    SubtaskModel.deleted_at.is_(None),
                    SubtaskModel.task_id.in_(
                        select(TaskModel.id).where(
                            TaskModel.deleted_at.is_(None),
                            TaskModel.activity_id.in_(
                                select(ActivityModel.id).where(
                                    ActivityModel.milestone_id == milestone_id,
                                    ActivityModel.deleted_at.is_(None),
                                )
                            ),
                        )
                    ),
                )),
            ],
            cascade_deleted_at=cascade_ts,
        )

        self.db.commit()
        self.db.refresh(m)
        return self._to_domain(m)
