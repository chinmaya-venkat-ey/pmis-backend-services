"""Create a task under an activity. Validates ``depends_on`` against the
hierarchy rule: target tasks must live in the same project, and the source's
parent activity must already depend on the target's parent activity (per the
activity_dependencies edge set). Same-activity targets are always allowed."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.task_repository import TaskRepository
from .....shared.date_rules import validate_entity_dates, validate_resource_dates
from .....domain.tasks.task import (
    Task,
    TASK_TYPE_RESOURCE,
    RESOURCE_MODE_COUNT,
    RESOURCE_MODE_DETAILS,
)
from .....domain.tasks.task_resource import TaskResource


def _validate_task_deps_hierarchy(
    db: Session,
    *,
    source_activity_id: str,
    project_id: str,
    target_task_ids: List[str],
) -> None:
    """Ensure each target task lives in the same project AND its parent
    activity is referenced by the source's parent activity in
    activity_dependencies. Same-activity targets are allowed without an
    activity-level edge.
    """
    if not target_task_ids:
        return
    dep_repo = DependencyRepository(db)
    found = dep_repo.existing_target_tasks(project_id, target_task_ids)
    if len(found) != len({tid for tid in target_task_ids if tid}):
        ok_ids = {tid for tid, _ in found}
        missing = [tid for tid in target_task_ids if tid and tid not in ok_ids]
        raise ValidationError(
            f"Unknown or out-of-project task dependency target(s): "
            f"{', '.join(missing)}"
        )
    for tid, parent_act in found:
        if not dep_repo.activity_pair_is_dependent(source_activity_id, parent_act):
            raise ValidationError(
                f"Cannot add task dependency on task '{tid}': the source's "
                f"parent activity does not depend on that task's parent "
                f"activity. Add the activity-level dependency first."
            )


def create_task(
    db: Session,
    *,
    activity_id: str,
    name: str,
    description: Optional[str],
    start_date: datetime,
    end_date: datetime,
    actual_start_date: Optional[datetime],
    actual_end_date: Optional[datetime],
    position: Optional[int],
    resource_mode: Optional[str],
    resource_count: Optional[int],
    resource: Optional[Dict[str, Any]],
    current_user_id: Optional[int],
    depends_on: Optional[List[str]] = None,
    # ``type`` is no longer accepted in the API body — the task inherits its
    # parent activity's type. Service callers may still pass an explicit
    # ``type`` to support a future cross-type-mapping endpoint; when None,
    # the parent activity's type is used.
    type: Optional[str] = None,
) -> Tuple[Task, Optional[TaskResource]]:
    activity = (
        db.query(ActivityModel)
        .filter(ActivityModel.id == activity_id)
        .filter(ActivityModel.deleted_at.is_(None))
        .first()
    )
    if activity is None:
        raise NotFoundError("The activity could not be found.")
    assert_task_subtask_writable(db, activity.project_id)

    # Inherit the type from the parent activity unless the caller (a future
    # cross-type-mapping path) explicitly passes one. The body schema strips
    # ``type`` so the only producer for now is the controller, which never
    # passes it. The activity's stored type is the source of truth.
    if type is None:
        type = activity.type
    # Cross-field validation: when the inherited type is non-resource, the
    # caller must NOT have supplied resource-mode-only fields.
    if type != TASK_TYPE_RESOURCE:
        if resource_mode is not None:
            raise ValidationError(
                "resourceMode is only valid when the parent activity's type "
                "is 'resource'. The parent activity here is "
                f"'{activity.type}', so omit resourceMode."
            )
        if resource_count is not None:
            raise ValidationError(
                "resourceCount is only valid when the parent activity's type "
                "is 'resource'."
            )
        if resource is not None:
            raise ValidationError(
                "resource details are only valid when the parent activity's "
                "type is 'resource'."
            )
    else:
        # Inherited type is 'resource' — caller must supply a mode + the
        # matching shape.
        if resource_mode is None:
            raise ValidationError(
                "resourceMode is required when the parent activity is a "
                "resource activity. Use 'count' or 'details'."
            )
        if resource_mode == RESOURCE_MODE_COUNT:
            if resource_count is None:
                raise ValidationError(
                    "resourceCount is required when resourceMode is 'count'."
                )
            if resource is not None:
                raise ValidationError(
                    "resource details should be omitted when resourceMode "
                    "is 'count'."
                )
        else:  # RESOURCE_MODE_DETAILS
            if resource is None:
                raise ValidationError(
                    "resource details are required when resourceMode is "
                    "'details'."
                )
            if resource_count is not None:
                raise ValidationError(
                    "resourceCount should be omitted when resourceMode is "
                    "'details'."
                )

    project = db.query(ProjectModel).filter(ProjectModel.id == activity.project_id).first()
    if project is None or project.start_date is None:
        raise ValidationError(
            "The project this task belongs to could not be found or has no start date."
        )

    validate_entity_dates(
        entity_start=start_date,
        entity_end=end_date,
        actual_start=actual_start_date,
        actual_end=actual_end_date,
        parent_start_date=activity.start_date,
        project_start_date=project.start_date,
        entity_label="task",
        parent_label="activity",
    )

    if resource is not None:
        validate_resource_dates(
            onboard=resource.get("onboard_date"),
            actual_onboard=resource.get("actual_onboard_date"),
            offboard=resource.get("offboard_date"),
            actual_offboard=resource.get("actual_offboard_date"),
            project_start_date=project.start_date,
        )

    # Validate dependsOn BEFORE inserting the task row.
    desired_deps: List[str] = []
    if depends_on is not None:
        candidates = [d for d in dict.fromkeys(depends_on) if d]
        # No self-edge needed (new id doesn't exist yet); cycle impossible.
        _validate_task_deps_hierarchy(
            db,
            source_activity_id=activity_id,
            project_id=activity.project_id,
            target_task_ids=candidates,
        )
        desired_deps = candidates

    repo = TaskRepository(db)
    pos = position if position is not None else repo.next_position(activity_id)

    store_mode = resource_mode if type == TASK_TYPE_RESOURCE else None
    store_count = resource_count if (
        type == TASK_TYPE_RESOURCE and resource_mode == RESOURCE_MODE_COUNT
    ) else None

    task = repo.create(
        project_id=activity.project_id,
        activity_id=activity_id,
        name=name.strip(),
        description=description,
        type=type,
        start_date=start_date,
        end_date=end_date,
        actual_start_date=actual_start_date,
        actual_end_date=actual_end_date,
        position=pos,
        created_by=current_user_id,
        resource_mode=store_mode,
        resource_count=store_count,
    )
    resource_domain = None
    if type == TASK_TYPE_RESOURCE and resource_mode == RESOURCE_MODE_DETAILS:
        resource_domain = repo.insert_resource(
            task_id=task.id, project_id=activity.project_id, data=resource,
        )

    if desired_deps:
        DependencyRepository(db).set_task_dependencies(
            task.id, activity.project_id, desired_deps,
            actor_id=current_user_id,
        )

    db.commit()
    refreshed = repo.get_by_id(task.id)
    out = refreshed or task
    out.depends_on = DependencyRepository(db).list_task_dependencies(task.id)
    return out, resource_domain
