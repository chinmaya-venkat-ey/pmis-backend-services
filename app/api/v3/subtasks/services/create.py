"""Create a subtask under a task. Enforces dependsOn hierarchy: target subtasks
must live in the same project, and the source's parent task must already
depend on the target's parent task (per task_dependencies). Same-task targets
are always allowed."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository
from .....shared.date_rules import validate_entity_dates, validate_resource_dates
from .....domain.subtasks.subtask import (
    Subtask,
    SUBTASK_TYPE_RESOURCE,
    RESOURCE_MODE_COUNT,
    RESOURCE_MODE_DETAILS,
)
from .....domain.subtasks.subtask_resource import SubtaskResource


def _validate_subtask_deps_hierarchy(
    db: Session,
    *,
    source_task_id: str,
    project_id: str,
    target_subtask_ids: List[str],
) -> None:
    """Targets must live in the same project AND source.task must already
    depend on target.task. Same-task is always allowed."""
    if not target_subtask_ids:
        return
    dep_repo = DependencyRepository(db)
    found = dep_repo.existing_target_subtasks(project_id, target_subtask_ids)
    if len(found) != len({sid for sid in target_subtask_ids if sid}):
        ok_ids = {sid for sid, _ in found}
        missing = [sid for sid in target_subtask_ids if sid and sid not in ok_ids]
        raise ValidationError(
            f"Unknown or out-of-project subtask dependency target(s): "
            f"{', '.join(missing)}"
        )
    for sid, parent_task in found:
        if not dep_repo.task_pair_is_dependent(source_task_id, parent_task):
            raise ValidationError(
                f"Cannot add subtask dependency on subtask '{sid}': the "
                f"source's parent task does not depend on that subtask's "
                f"parent task. Add the task-level dependency first."
            )


def create_subtask(
    db: Session,
    *,
    task_id: str,
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
    # ``type`` is no longer accepted via the API body — subtasks inherit
    # type from the parent task. Service callers may still pass an
    # explicit type to support a future cross-type-mapping endpoint.
    type: Optional[str] = None,
) -> Tuple[Subtask, Optional[SubtaskResource]]:
    task = (
        db.query(TaskModel)
        .filter(TaskModel.id == task_id)
        .filter(TaskModel.deleted_at.is_(None))
        .first()
    )
    if task is None:
        raise NotFoundError("The task could not be found.")
    assert_task_subtask_writable(db, task.project_id)

    # Inherit type from the parent task when caller didn't pass one.
    if type is None:
        type = task.type
    if type != SUBTASK_TYPE_RESOURCE:
        if resource_mode is not None:
            raise ValidationError(
                "resourceMode is only valid when the parent task's type is "
                f"'resource'. Parent task type here is '{task.type}'."
            )
        if resource_count is not None:
            raise ValidationError(
                "resourceCount is only valid when the parent task's type "
                "is 'resource'."
            )
        if resource is not None:
            raise ValidationError(
                "resource details are only valid when the parent task's "
                "type is 'resource'."
            )
    else:
        if resource_mode is None:
            raise ValidationError(
                "resourceMode is required when the parent task is a "
                "resource task. Use 'count' or 'details'."
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
        else:
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

    project = db.query(ProjectModel).filter(ProjectModel.id == task.project_id).first()
    if project is None or project.start_date is None:
        raise ValidationError(
            "The project this subtask belongs to could not be found or has no start date."
        )

    validate_entity_dates(
        entity_start=start_date, entity_end=end_date,
        actual_start=actual_start_date, actual_end=actual_end_date,
        parent_start_date=task.start_date,
        project_start_date=project.start_date,
        entity_label="subtask",
        parent_label="task",
    )

    if resource is not None:
        validate_resource_dates(
            onboard=resource.get("onboard_date"),
            actual_onboard=resource.get("actual_onboard_date"),
            offboard=resource.get("offboard_date"),
            actual_offboard=resource.get("actual_offboard_date"),
            project_start_date=project.start_date,
        )

    desired_deps: List[str] = []
    if depends_on is not None:
        candidates = [d for d in dict.fromkeys(depends_on) if d]
        _validate_subtask_deps_hierarchy(
            db,
            source_task_id=task_id,
            project_id=task.project_id,
            target_subtask_ids=candidates,
        )
        desired_deps = candidates

    repo = SubtaskRepository(db)
    pos = position if position is not None else repo.next_position(task_id)

    store_mode = resource_mode if type == SUBTASK_TYPE_RESOURCE else None
    store_count = resource_count if (
        type == SUBTASK_TYPE_RESOURCE and resource_mode == RESOURCE_MODE_COUNT
    ) else None

    subtask = repo.create(
        project_id=task.project_id,
        task_id=task_id,
        name=name.strip(),
        description=description,
        type=type,
        start_date=start_date, end_date=end_date,
        actual_start_date=actual_start_date, actual_end_date=actual_end_date,
        position=pos,
        created_by=current_user_id,
        resource_mode=store_mode,
        resource_count=store_count,
    )
    resource_domain = None
    if type == SUBTASK_TYPE_RESOURCE and resource_mode == RESOURCE_MODE_DETAILS:
        resource_domain = repo.insert_resource(
            subtask_id=subtask.id, project_id=task.project_id, data=resource,
        )

    if desired_deps:
        DependencyRepository(db).set_subtask_dependencies(
            subtask.id, task.project_id, desired_deps,
            actor_id=current_user_id,
        )

    db.commit()
    refreshed = repo.get_by_id(subtask.id)
    out = refreshed or subtask
    out.depends_on = DependencyRepository(db).list_subtask_dependencies(subtask.id)
    return out, resource_domain
