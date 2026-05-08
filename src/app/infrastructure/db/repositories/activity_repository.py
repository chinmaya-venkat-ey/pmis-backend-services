"""Activity repository (with resource sub-entity ops)."""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models.activity import ActivityModel
from ..models.activity_resource import ActivityResourceModel
from ..models.task import TaskModel
from ..models.task_resource import TaskResourceModel
from ..models.subtask import SubtaskModel
from ..models.subtask_resource import SubtaskResourceModel
from ....domain.activities.activity import Activity
from ....domain.activities.activity_resource import ActivityResource
from ....shared.comments_attachments_cascade import (
    cascade_restore_comments_and_attachments,
    cascade_soft_delete_comments_and_attachments,
)


class ActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------- conversions ----------

    def _to_domain(self, a: ActivityModel) -> Activity:
        return Activity(
            id=a.id,
            project_id=a.project_id,
            milestone_id=a.milestone_id,
            name=a.name,
            description=a.description,
            type=a.type,
            start_date=a.start_date,
            end_date=a.end_date,
            actual_start_date=a.actual_start_date,
            actual_end_date=a.actual_end_date,
            position=a.position,
            resource_mode=a.resource_mode,
            resource_count=a.resource_count,
            status=getattr(a, "status", None),
            # depends_on is populated by the service layer from
            # DependencyRepository.list_activity_dependencies(...).
            depends_on=[],
            owner_division=getattr(a, "owner_division", None),
            concerned_division=getattr(a, "concerned_division", None),
            concerned_divisions=getattr(a, "concerned_divisions", None),
            vendor_id=getattr(a, "vendor_id", None),
            priority=getattr(a, "priority", None),
            created_at=a.created_at,
            updated_at=a.updated_at,
            created_by=a.created_by,
            updated_by=a.updated_by,
            deleted_at=a.deleted_at,
        )

    def _resource_to_domain(self, r: ActivityResourceModel) -> ActivityResource:
        return ActivityResource(
            id=r.id,
            activity_id=r.activity_id,
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
            type_of_resource_id=getattr(r, "type_of_resource_id", None),
            division=getattr(r, "division", None),
            division_other=getattr(r, "division_other", None),
            created_at=r.created_at,
            updated_at=r.updated_at,
            deleted_at=r.deleted_at,
        )

    # ---------- reads ----------

    def get_by_id(self, activity_id: str, include_deleted: bool = False) -> Optional[Activity]:
        q = self.db.query(ActivityModel).filter(ActivityModel.id == activity_id)
        if not include_deleted:
            q = q.filter(ActivityModel.deleted_at.is_(None))
        row = q.first()
        return self._to_domain(row) if row else None

    def get_model(self, activity_id: str, include_deleted: bool = False) -> Optional[ActivityModel]:
        q = self.db.query(ActivityModel).filter(ActivityModel.id == activity_id)
        if not include_deleted:
            q = q.filter(ActivityModel.deleted_at.is_(None))
        return q.first()

    def list_by_milestone(
        self, milestone_id: str, offset: int = 0, limit: int = 20,
        include_deleted: bool = False,
    ) -> Tuple[List[Activity], int]:
        base = self.db.query(ActivityModel).filter(ActivityModel.milestone_id == milestone_id)
        if not include_deleted:
            base = base.filter(ActivityModel.deleted_at.is_(None))
        total = base.with_entities(func.count(ActivityModel.id)).scalar() or 0
        rows = (
            base.order_by(ActivityModel.position.asc(), ActivityModel.id.asc())
            .offset(offset).limit(limit).all()
        )
        return [self._to_domain(r) for r in rows], total

    def next_position(self, milestone_id: str) -> int:
        cur = (
            self.db.query(func.max(ActivityModel.position))
            .filter(ActivityModel.milestone_id == milestone_id)
            .filter(ActivityModel.deleted_at.is_(None))
            .scalar()
        )
        return (cur or 0) + 1

    def position_taken(self, milestone_id: str, position: int) -> bool:
        """True iff a live activity in ``milestone_id`` already occupies
        ``position``. Lets the create service auto-bump caller-supplied
        positions that would otherwise trip the unique index — see
        ``MilestoneRepository.position_taken`` for the same rationale.
        """
        return self.db.query(ActivityModel.id).filter(
            ActivityModel.milestone_id == milestone_id,
            ActivityModel.position == position,
            ActivityModel.deleted_at.is_(None),
        ).first() is not None

    def get_live_resource(self, activity_id: str) -> Optional[ActivityResource]:
        row = (
            self.db.query(ActivityResourceModel)
            .filter(ActivityResourceModel.activity_id == activity_id)
            .filter(ActivityResourceModel.deleted_at.is_(None))
            .first()
        )
        return self._resource_to_domain(row) if row else None

    # ---------- writes ----------

    def create(
        self, *,
        project_id: str, milestone_id: str, name: str, description: Optional[str],
        type: Optional[str], start_date: datetime, end_date: datetime,
        actual_start_date: Optional[datetime], actual_end_date: Optional[datetime],
        position: int, created_by: Optional[str],
        resource_mode: Optional[str] = None,
        resource_count: Optional[int] = None,
        status: Optional[str] = None,
        # Doc 38 additions — all optional.
        owner_division: Optional[str] = None,
        concerned_division: Optional[str] = None,
        # Doc 39: list of division codes; primary write target.
        concerned_divisions: Optional[list] = None,
        vendor_id: Optional[str] = None,
        # Doc 41: priority code from the priorities catalog.
        priority: Optional[str] = None,
    ) -> Activity:
        a = ActivityModel(
            project_id=project_id,
            milestone_id=milestone_id,
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
            owner_division=owner_division,
            concerned_division=concerned_division,
            concerned_divisions=concerned_divisions,
            vendor_id=vendor_id,
            priority=priority,
            created_by=created_by,
            updated_by=created_by,
        )
        self.db.add(a)
        self.db.flush()  # get the id without committing -- caller may also create resource in same txn
        return self._to_domain(a)

    def update(self, activity_id: str, *, updates: dict, updated_by: Optional[str]) -> Activity:
        a = self.get_model(activity_id)
        if a is None:
            raise LookupError(f"Activity {activity_id} not found")
        for k, v in updates.items():
            setattr(a, k, v)
        a.updated_by = updated_by
        self.db.flush()
        return self._to_domain(a)

    # ---------- resource sub-entity ----------

    def insert_resource(
        self, *,
        activity_id: str, project_id: str, data: dict,
    ) -> ActivityResource:
        r = ActivityResourceModel(
            activity_id=activity_id,
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
            type_of_resource_id=data.get("type_of_resource_id"),
            division=data.get("division"),
            division_other=data.get("division_other"),
        )
        self.db.add(r)
        self.db.flush()
        return self._resource_to_domain(r)

    def upsert_resource(
        self, *, activity_id: str, project_id: str, data: dict,
    ) -> ActivityResource:
        """
        Insert a fresh resource row if no live one exists for this activity,
        else update the live row. Keyed on the partial-unique index
        (activity_id) WHERE deleted_at IS NULL.
        """
        existing = (
            self.db.query(ActivityResourceModel)
            .filter(
                ActivityResourceModel.activity_id == activity_id,
                ActivityResourceModel.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            return self.insert_resource(activity_id=activity_id, project_id=project_id, data=data)
        # update in place
        for field in (
            "resource_name", "onboard_date", "actual_onboard_date",
            "offboard_date", "actual_offboard_date",
            "position", "designation", "job_role", "qualification", "experience_years",
            "type_of_resource_id", "division", "division_other",
        ):
            if field in data:
                setattr(existing, field, data[field])
        existing.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return self._resource_to_domain(existing)

    def soft_delete_live_resource(self, activity_id: str) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(
            update(ActivityResourceModel)
            .where(
                ActivityResourceModel.activity_id == activity_id,
                ActivityResourceModel.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
        )

    # ---------- delete + cascade (activity subtree) ----------

    def soft_delete_with_cascade(self, activity_id: str, deleted_by: Optional[str]) -> None:
        now = datetime.now(timezone.utc)
        task_ids = select(TaskModel.id).where(
            TaskModel.activity_id == activity_id,
            TaskModel.deleted_at.is_(None),
        )
        subtask_ids = select(SubtaskModel.id).where(
            SubtaskModel.task_id.in_(task_ids),
            SubtaskModel.deleted_at.is_(None),
        )

        self.db.execute(update(SubtaskResourceModel).where(
            SubtaskResourceModel.subtask_id.in_(subtask_ids),
            SubtaskResourceModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now))
        self.db.execute(update(TaskResourceModel).where(
            TaskResourceModel.task_id.in_(task_ids),
            TaskResourceModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now))
        self.db.execute(update(ActivityResourceModel).where(
            ActivityResourceModel.activity_id == activity_id,
            ActivityResourceModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now))
        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.task_id.in_(task_ids),
            SubtaskModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now, updated_by=deleted_by))
        self.db.execute(update(TaskModel).where(
            TaskModel.activity_id == activity_id,
            TaskModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now, updated_by=deleted_by))
        self.db.execute(update(ActivityModel).where(
            ActivityModel.id == activity_id,
            ActivityModel.deleted_at.is_(None),
        ).values(deleted_at=now, updated_at=now, updated_by=deleted_by))

        # Doc 34: cascade comments + attachments under the activity
        # subtree we just soft-deleted. Re-deriving the subtree by
        # ``deleted_at == now`` finds exactly the rows this cascade
        # touched, so the matching restore-cascade can identify them.
        cascade_soft_delete_comments_and_attachments(
            self.db,
            targets=[
                ("activity", activity_id),
                ("task", select(TaskModel.id).where(
                    TaskModel.activity_id == activity_id,
                    TaskModel.deleted_at == now,
                )),
                ("subtask", select(SubtaskModel.id).where(
                    SubtaskModel.deleted_at == now,
                    SubtaskModel.task_id.in_(
                        select(TaskModel.id).where(
                            TaskModel.activity_id == activity_id,
                            TaskModel.deleted_at == now,
                        )
                    ),
                )),
            ],
            deleted_by=deleted_by,
            now=now,
        )

        self.db.commit()

    def restore(self, activity_id: str, restored_by: Optional[int]) -> Activity:
        """
        Restore the activity + every T/S/resource/comment/attachment that
        was soft-deleted as part of the same cascade event (doc 34).
        Dep edges are NOT auto-restored.
        """
        a = self.get_model(activity_id, include_deleted=True)
        if a is None:
            raise LookupError(f"Activity {activity_id} not found")
        if a.deleted_at is None:
            return self._to_domain(a)

        cascade_ts = a.deleted_at
        now = datetime.now(timezone.utc)

        a.deleted_at = None
        a.updated_at = now
        a.updated_by = restored_by
        self.db.flush()

        self.db.execute(update(TaskModel).where(
            TaskModel.activity_id == activity_id,
            TaskModel.deleted_at == cascade_ts,
        ).values(deleted_at=None, updated_at=now, updated_by=restored_by))
        self.db.execute(update(SubtaskModel).where(
            SubtaskModel.deleted_at == cascade_ts,
            SubtaskModel.task_id.in_(
                select(TaskModel.id).where(
                    TaskModel.activity_id == activity_id,
                    TaskModel.deleted_at.is_(None),
                )
            ),
        ).values(deleted_at=None, updated_at=now, updated_by=restored_by))

        # Resources.
        self.db.execute(update(ActivityResourceModel).where(
            ActivityResourceModel.activity_id == activity_id,
            ActivityResourceModel.deleted_at == cascade_ts,
        ).values(deleted_at=None, updated_at=now))
        self.db.execute(update(TaskResourceModel).where(
            TaskResourceModel.deleted_at == cascade_ts,
            TaskResourceModel.task_id.in_(
                select(TaskModel.id).where(
                    TaskModel.activity_id == activity_id,
                    TaskModel.deleted_at.is_(None),
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
                            TaskModel.activity_id == activity_id,
                            TaskModel.deleted_at.is_(None),
                        )
                    ),
                )
            ),
        ).values(deleted_at=None, updated_at=now))

        cascade_restore_comments_and_attachments(
            self.db,
            targets=[
                ("activity", activity_id),
                ("task", select(TaskModel.id).where(
                    TaskModel.activity_id == activity_id,
                    TaskModel.deleted_at.is_(None),
                )),
                ("subtask", select(SubtaskModel.id).where(
                    SubtaskModel.deleted_at.is_(None),
                    SubtaskModel.task_id.in_(
                        select(TaskModel.id).where(
                            TaskModel.activity_id == activity_id,
                            TaskModel.deleted_at.is_(None),
                        )
                    ),
                )),
            ],
            cascade_deleted_at=cascade_ts,
        )

        self.db.commit()
        self.db.refresh(a)
        return self._to_domain(a)
