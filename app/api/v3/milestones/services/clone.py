"""
Deep-clone the M/A/T/S subtree from one project to another. Used by the
projects-side `Create Version` endpoint.

EXPOSED TO THE PROJECTS MODULE. Call from projects.services.create_version
INSIDE your transaction, AFTER the new project row exists.

Behaviour:
  - Clones only LIVE (deleted_at IS NULL) rows from the source.
  - Rewrites all parent FKs to point at the newly-cloned ancestors.
  - Sets project_id on every cloned row to the target project.
  - Resets actual_start_date / actual_end_date to NULL on all entities.
  - Resets actual_onboard_date / actual_offboard_date to NULL on resources.
  - Preserves planned dates, type, position, name, description.
  - Does NOT copy audit metadata (created_at, created_by, etc.) --
    timestamps come from the new INSERTs; created_by is set to the caller.
"""
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.activity_resource import ActivityResourceModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.models.task_resource import TaskResourceModel
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.models.subtask_resource import SubtaskResourceModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)


def clone_tree_for_version(
    db: Session,
    *,
    source_project_id: str,
    target_project_id: str,
    created_by: Optional[int] = None,
) -> Dict[str, int]:
    """
    Clone all live M/A/T/S + resource rows from source project to target.

    Returns a small summary dict (counts per table) for logging / audit.

    Does NOT commit; caller controls transaction.
    """
    now = datetime.now(timezone.utc)
    counts = {
        "milestones": 0, "activities": 0, "tasks": 0, "subtasks": 0,
        "activity_resources": 0, "task_resources": 0, "subtask_resources": 0,
    }

    # --- Milestones ---
    src_milestones = db.execute(
        select(MilestoneModel)
        .where(MilestoneModel.project_id == source_project_id,
               MilestoneModel.deleted_at.is_(None))
        .order_by(MilestoneModel.id.asc())
    ).scalars().all()
    milestone_map: Dict[int, int] = {}
    for src in src_milestones:
        new = MilestoneModel(
            project_id=target_project_id,
            name=src.name,
            description=src.description,
            start_date=src.start_date,
            end_date=src.end_date,
            position=src.position,
            # Reset status on a new version — work hasn't happened yet.
            status="not_completed",
            # `depends` references sibling milestones; the cloned milestones
            # have new ids, so the reference list is meaningless. Drop it on
            # clone to avoid carrying stale ids across.
            depends=None,
            # Lineage — points back to the baseline row we cloned from, so
            # later baseline edits can locate this copy and propagate.
            cloned_from_id=src.id,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(new)
        db.flush()
        milestone_map[src.id] = new.id
        counts["milestones"] += 1

    # --- Activities ---
    if milestone_map:
        src_activities = db.execute(
            select(ActivityModel)
            .where(ActivityModel.project_id == source_project_id,
                   ActivityModel.deleted_at.is_(None))
            .order_by(ActivityModel.id.asc())
        ).scalars().all()
    else:
        src_activities = []
    activity_map: Dict[int, int] = {}
    for src in src_activities:
        new_ms = milestone_map.get(src.milestone_id)
        if new_ms is None:
            # Orphan activity (its milestone was deleted at source). Skip.
            continue
        new = ActivityModel(
            project_id=target_project_id,
            milestone_id=new_ms,
            name=src.name,
            description=src.description,
            type=src.type,
            start_date=src.start_date,
            end_date=src.end_date,
            actual_start_date=None,
            actual_end_date=None,
            position=src.position,
            resource_mode=src.resource_mode,
            resource_count=src.resource_count,
            # Standard-only column: reset status to 'not_completed' (default
            # for new work). Activity dependency edges are cloned separately
            # below via DependencyRepository.clone_activity_dependencies_for_version.
            status="not_completed" if src.type == "standard" else None,
            # Lineage — points back to the baseline activity row.
            cloned_from_id=src.id,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(new)
        db.flush()
        activity_map[src.id] = new.id
        counts["activities"] += 1

    # --- Activity resources ---
    if activity_map:
        src_ar = db.execute(
            select(ActivityResourceModel)
            .where(ActivityResourceModel.project_id == source_project_id,
                   ActivityResourceModel.deleted_at.is_(None))
            .order_by(ActivityResourceModel.id.asc())
        ).scalars().all()
        for src in src_ar:
            new_act = activity_map.get(src.activity_id)
            if new_act is None:
                continue
            db.add(ActivityResourceModel(
                activity_id=new_act,
                project_id=target_project_id,
                resource_name=src.resource_name,
                onboard_date=src.onboard_date,
                actual_onboard_date=None,
                offboard_date=src.offboard_date,
                actual_offboard_date=None,
                position=src.position,
                designation=src.designation,
                job_role=src.job_role,
                qualification=src.qualification,
                experience_years=src.experience_years,
                # Classification fields carry through — a cloned version
                # inherits the same "type of resource" and division labels.
                type_of_resource_id=getattr(src, "type_of_resource_id", None),
                division=getattr(src, "division", None),
                division_other=getattr(src, "division_other", None),
                created_at=now,
                updated_at=now,
            ))
            counts["activity_resources"] += 1

    # --- Tasks ---
    if activity_map:
        src_tasks = db.execute(
            select(TaskModel)
            .where(TaskModel.project_id == source_project_id,
                   TaskModel.deleted_at.is_(None))
            .order_by(TaskModel.id.asc())
        ).scalars().all()
    else:
        src_tasks = []
    task_map: Dict[int, int] = {}
    for src in src_tasks:
        new_act = activity_map.get(src.activity_id)
        if new_act is None:
            continue
        new = TaskModel(
            project_id=target_project_id,
            activity_id=new_act,
            name=src.name,
            description=src.description,
            type=src.type,
            start_date=src.start_date,
            end_date=src.end_date,
            actual_start_date=None,
            actual_end_date=None,
            position=src.position,
            resource_mode=src.resource_mode,
            resource_count=src.resource_count,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(new)
        db.flush()
        task_map[src.id] = new.id
        counts["tasks"] += 1

    # --- Task resources ---
    if task_map:
        src_tr = db.execute(
            select(TaskResourceModel)
            .where(TaskResourceModel.project_id == source_project_id,
                   TaskResourceModel.deleted_at.is_(None))
            .order_by(TaskResourceModel.id.asc())
        ).scalars().all()
        for src in src_tr:
            new_t = task_map.get(src.task_id)
            if new_t is None:
                continue
            db.add(TaskResourceModel(
                task_id=new_t,
                project_id=target_project_id,
                resource_name=src.resource_name,
                onboard_date=src.onboard_date,
                actual_onboard_date=None,
                offboard_date=src.offboard_date,
                actual_offboard_date=None,
                position=src.position,
                designation=src.designation,
                job_role=src.job_role,
                qualification=src.qualification,
                experience_years=src.experience_years,
                created_at=now,
                updated_at=now,
            ))
            counts["task_resources"] += 1

    # --- Subtasks ---
    if task_map:
        src_subtasks = db.execute(
            select(SubtaskModel)
            .where(SubtaskModel.project_id == source_project_id,
                   SubtaskModel.deleted_at.is_(None))
            .order_by(SubtaskModel.id.asc())
        ).scalars().all()
    else:
        src_subtasks = []
    subtask_map: Dict[int, int] = {}
    for src in src_subtasks:
        new_t = task_map.get(src.task_id)
        if new_t is None:
            continue
        new = SubtaskModel(
            project_id=target_project_id,
            task_id=new_t,
            name=src.name,
            description=src.description,
            type=src.type,
            start_date=src.start_date,
            end_date=src.end_date,
            actual_start_date=None,
            actual_end_date=None,
            position=src.position,
            resource_mode=src.resource_mode,
            resource_count=src.resource_count,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(new)
        db.flush()
        subtask_map[src.id] = new.id
        counts["subtasks"] += 1

    # --- Activity dependencies ---
    # Clone the baseline's activity_dependencies edges into the new version's
    # scope, rewriting source/target ids via activity_map. Tasks and subtasks
    # don't exist on a fresh version (they're version-owned and created after
    # clone), so task/subtask dependency tables are intentionally not
    # populated here.
    if activity_map:
        DependencyRepository(db).clone_activity_dependencies_for_version(
            source_project_id=source_project_id,
            target_project_id=target_project_id,
            activity_id_map=activity_map,
        )

    # --- Subtask resources ---
    if subtask_map:
        src_sr = db.execute(
            select(SubtaskResourceModel)
            .where(SubtaskResourceModel.project_id == source_project_id,
                   SubtaskResourceModel.deleted_at.is_(None))
            .order_by(SubtaskResourceModel.id.asc())
        ).scalars().all()
        for src in src_sr:
            new_s = subtask_map.get(src.subtask_id)
            if new_s is None:
                continue
            db.add(SubtaskResourceModel(
                subtask_id=new_s,
                project_id=target_project_id,
                resource_name=src.resource_name,
                onboard_date=src.onboard_date,
                actual_onboard_date=None,
                offboard_date=src.offboard_date,
                actual_offboard_date=None,
                position=src.position,
                designation=src.designation,
                job_role=src.job_role,
                qualification=src.qualification,
                experience_years=src.experience_years,
                created_at=now,
                updated_at=now,
            ))
            counts["subtask_resources"] += 1

    return counts
