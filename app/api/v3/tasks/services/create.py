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
    collect_milestone_forward_violations,
    raise_milestone_forward_if_violations,
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


# Doc 38: task status accepts any string on the wire (no catalog yet).
# The only enforced rule on create is the completion gate — if the
# caller wants to start the row off as "completed", every dep target
# must already be "completed" too.
_STATUS_COMPLETED = "completed"
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
    # Unified create/update shape: status is now optional on create.
    status: Optional[str] = None,
    # Doc 41 follow-up: optional single assignee (active user UUID).
    assigned_to: Optional[str] = None,
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

    # Doc 41 follow-up: validate the assignee (if any). Must be a live,
    # active user from the users catalog. Independent per-level: no
    # cascade from / to subtasks.
    if assigned_to is not None:
        from .....shared.assignee import validate_assignable_user_id
        validate_assignable_user_id(db, assigned_to)

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

    # Status-completion gate: if the caller wants to start the row off
    # as 'completed', every dep target must already be completed too.
    # Mirrors the PATCH-time gate in update_task.
    if status == _STATUS_COMPLETED and desired_deps:
        rows = (
            db.query(TaskModel.id, TaskModel.name, TaskModel.status)
            .filter(TaskModel.id.in_(desired_deps))
            .all()
        )
        blockers = [r for r in rows if (r[2] or "") != _STATUS_COMPLETED]
        if blockers:
            names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
            more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
            raise ValidationError(
                f"Cannot create this task as completed — the following "
                f"dependency target(s) are not yet completed: {names}{more}.",
            )

        # Doc 27: source.start_date >= target.end_date for every dep target.
        if desired_deps:
            target_rows = (
                db.query(
                    TaskModel.id, TaskModel.name,
                    TaskModel.start_date, TaskModel.end_date,
                )
                .filter(TaskModel.id.in_(desired_deps))
                .all()
            )
            label_index = build_label_index_for_project(db, activity.project_id)
            forward = [
                (label_index.label_of(KIND_TASK, tid) or tname, tstart, tend)
                for (tid, tname, tstart, tend) in target_rows
            ]
            starts_v, ends_v = collect_milestone_forward_violations(
                source_start=start_date, source_end=end_date, targets=forward,
            )
            raise_milestone_forward_if_violations(
                starts_v, ends_v,
                source_label=f"Task '{name.strip()}'",
                source_start=start_date, source_end=end_date,
                kind_singular="task",
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
        status=status,
        assigned_to=assigned_to,
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
