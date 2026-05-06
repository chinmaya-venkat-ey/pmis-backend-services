"""Create a task under an activity. ``depends_on`` rules: target tasks
must live in the same project, source != target (cycle prevention kicks
in on update). The legacy parent-activity hierarchy rule was dropped in
doc 24 — tasks may now depend on any task in the same project regardless
of parent activity linkage."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.task_repository import TaskRepository
from .....shared.date_rules import validate_entity_dates, validate_resource_dates
from .....shared.dep_date_rules import (
    collect_forward_violations,
    raise_forward_if_violations,
)
from .....shared.labels import (
    KIND_TASK,
    build_label_index_for_project,
    resolve_labels_to_ids,
)
from .....domain.tasks.task import (
    Task,
    TASK_TYPE_RESOURCE,
    RESOURCE_MODE_COUNT,
    RESOURCE_MODE_DETAILS,
)
from .....domain.tasks.task_resource import TaskResource


def _validate_task_deps_same_project(
    db: Session,
    *,
    project_id: str,
    target_task_ids: List[str],
) -> None:
    """Targets must live in the same project. Doc 24: dropped the
    parent-activity hierarchy rule — any task in the project is a valid
    dependency target now."""
    if not target_task_ids:
        return
    dep_repo = DependencyRepository(db)
    found = dep_repo.existing_target_tasks(project_id, target_task_ids)
    ok_ids = {tid for tid, _ in found}
    missing = [tid for tid in target_task_ids if tid and tid not in ok_ids]
    if missing:
        raise ValidationError(
            f"Unknown or out-of-project task dependency target(s): "
            f"{', '.join(missing)}"
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

    # Validate dependsOn BEFORE inserting the task row. Accepts UUIDs or
    # labels (e.g. "T1.2.3") — see app/shared/labels.py.
    desired_deps: List[str] = []
    if depends_on is not None:
        candidates, _id_to_raw = resolve_labels_to_ids(
            db,
            project_id=activity.project_id,
            expected_kind=KIND_TASK,
            raw_inputs=depends_on,
        )
        # No self-edge / cycle needed (new id doesn't exist yet).
        _validate_task_deps_same_project(
            db,
            project_id=activity.project_id,
            target_task_ids=candidates,
        )
        desired_deps = candidates

        # Doc 27: source.start_date >= target.end_date for every dep target.
        if desired_deps:
            target_rows = (
                db.query(TaskModel.id, TaskModel.name, TaskModel.end_date)
                .filter(TaskModel.id.in_(desired_deps))
                .all()
            )
            label_index = build_label_index_for_project(db, activity.project_id)
            forward = [
                (label_index.label_of(KIND_TASK, tid) or tname, tend)
                for (tid, tname, tend) in target_rows
            ]
            raise_forward_if_violations(
                collect_forward_violations(
                    source_start=start_date, targets=forward,
                ),
                source_label=f"Task '{name.strip()}'",
                source_start=start_date,
            )

    repo = TaskRepository(db)
    # Doc 30 follow-up: auto-bump on position collision (see milestone
    # create service for full rationale).
    if position is None or repo.position_taken(activity_id, position):
        pos = repo.next_position(activity_id)
    else:
        pos = position

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

    # Doc 33: audit task creation at the project level so the project's
    # log shows every M/A/T/S write, not just M/A.
    from ...projects.services.audit import ACTION_TASK_CREATE, record_audit
    record_audit(
        db,
        project_id=activity.project_id,
        actor_id=current_user_id,
        action=ACTION_TASK_CREATE,
        before=None,
        after={
            "task_id": task.id,
            "activity_id": activity_id,
            "name": task.name,
            "type": task.type,
            "start_date": task.start_date.isoformat() if task.start_date else None,
            "end_date": task.end_date.isoformat() if task.end_date else None,
            "depends_on": list(desired_deps),
        },
    )
    db.commit()
    refreshed = repo.get_by_id(task.id)
    out = refreshed or task
    out.depends_on = DependencyRepository(db).list_task_dependencies(task.id)
    return out, resource_domain
