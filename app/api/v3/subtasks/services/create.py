"""Create a subtask. ``dependsOn`` rules: target subtasks must live in
the same project, source != target. The legacy parent-task hierarchy
rule was dropped in doc 24 — subtasks may now depend on any subtask in
the same project regardless of parent-task linkage.

Doc 24 also adds **nesting**: pass ``parent_subtask_id`` to attach the
new subtask under another subtask (any depth). When set, ``task_id`` is
inferred from the parent subtask's root task. Only one of
(``task_id``, ``parent_subtask_id``) should be supplied by the caller.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .....core.config import settings
from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository
from .....shared.date_rules import validate_entity_dates, validate_resource_dates
from .....shared.dep_date_rules import (
    collect_milestone_forward_violations,
    raise_milestone_forward_if_violations,
)
from .....shared.labels import (
    KIND_SUBTASK,
    build_label_index_for_project,
    resolve_labels_to_ids,
)
from .....domain.subtasks.subtask import (
    Subtask,
    SUBTASK_TYPE_RESOURCE,
    RESOURCE_MODE_COUNT,
    RESOURCE_MODE_DETAILS,
)
from .....domain.subtasks.subtask_resource import SubtaskResource


def _validate_subtask_deps_same_project(
    db: Session,
    *,
    project_id: str,
    target_subtask_ids: List[str],
) -> None:
    """Targets must live in the same project. Doc 24: dropped the
    parent-task hierarchy rule — any subtask in the project (top-level
    or nested at any depth) is a valid dependency target."""
    if not target_subtask_ids:
        return
    dep_repo = DependencyRepository(db)
    found = dep_repo.existing_target_subtasks(project_id, target_subtask_ids)
    ok_ids = {sid for sid, _ in found}
    missing = [sid for sid in target_subtask_ids if sid and sid not in ok_ids]
    if missing:
        raise ValidationError(
            f"Unknown or out-of-project subtask dependency target(s): "
            f"{', '.join(missing)}"
        )


def _resolve_parent(
    db: Session,
    *,
    task_id: Optional[str],
    parent_subtask_id: Optional[str],
) -> Tuple[TaskModel, Optional[SubtaskModel], int]:
    """Return ``(root_task, parent_subtask_or_None, depth_of_new_row)``.

    Top-level create: caller passes ``task_id``, ``parent_subtask_id=None``.
    Nested create: caller passes ``parent_subtask_id``; the root task is
    derived from the parent's ``task_id`` and depth is ``len(ancestors)+1``
    (parent's own ancestors + parent itself + the new row would be one
    more level beyond — but for the depth-cap check we measure where the
    new row sits, so depth = parent's ancestors + 1 + 1).
    """
    if (task_id is None) == (parent_subtask_id is None):
        raise ValidationError(
            "Exactly one of task_id or parent_subtask_id must be supplied."
        )

    if parent_subtask_id is not None:
        repo = SubtaskRepository(db)
        parent = repo.get_model(parent_subtask_id)
        if parent is None:
            raise NotFoundError("The parent subtask could not be found.")
        task = (
            db.query(TaskModel)
            .filter(TaskModel.id == parent.task_id)
            .filter(TaskModel.deleted_at.is_(None))
            .first()
        )
        if task is None:
            raise NotFoundError(
                "The root task for the parent subtask could not be found."
            )
        # Depth = (number of parent's ancestors) + 1 (parent itself)
        # + 1 (the new row sits one level below parent).
        new_depth = len(repo.ancestors(parent_subtask_id)) + 2
        return task, parent, new_depth

    task = (
        db.query(TaskModel)
        .filter(TaskModel.id == task_id)
        .filter(TaskModel.deleted_at.is_(None))
        .first()
    )
    if task is None:
        raise NotFoundError("The task could not be found.")
    return task, None, 1


def _enforce_depth_cap(new_depth: int) -> None:
    cap = settings.SUBTASK_MAX_NESTING_DEPTH
    if cap is not None and new_depth > cap:
        raise ValidationError(
            f"Subtask nesting depth cap exceeded: configured maximum is "
            f"{cap}, new subtask would sit at depth {new_depth}. Set "
            "SUBTASK_MAX_NESTING_DEPTH (env) higher or move the work."
        )


def create_subtask(
    db: Session,
    *,
    task_id: Optional[str] = None,
    parent_subtask_id: Optional[str] = None,
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
    # Unified create/update shape: status is now optional on create.
    status: Optional[str] = None,
    # Doc 41 follow-up: optional single assignee (active user UUID).
    assigned_to: Optional[str] = None,
) -> Tuple[Subtask, Optional[SubtaskResource]]:
    task, parent_subtask, new_depth = _resolve_parent(
        db, task_id=task_id, parent_subtask_id=parent_subtask_id,
    )
    assert_task_subtask_writable(db, task.project_id)
    _enforce_depth_cap(new_depth)

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

    # Date parent is the immediate parent (subtask if nested, task if top).
    parent_start = (
        parent_subtask.start_date if parent_subtask is not None else task.start_date
    )
    parent_label = "subtask" if parent_subtask is not None else "task"
    validate_entity_dates(
        entity_start=start_date, entity_end=end_date,
        actual_start=actual_start_date, actual_end=actual_end_date,
        parent_start_date=parent_start,
        project_start_date=project.start_date,
        entity_label="subtask",
        parent_label=parent_label,
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
    # active user. Independent per-level — applies the same to nested
    # subtasks; parent's assignee has no effect.
    if assigned_to is not None:
        from .....shared.assignee import validate_assignable_user_id
        validate_assignable_user_id(db, assigned_to)

    desired_deps: List[str] = []
    if depends_on is not None:
        candidates, _id_to_raw = resolve_labels_to_ids(
            db,
            project_id=task.project_id,
            expected_kind=KIND_SUBTASK,
            raw_inputs=depends_on,
        )
        _validate_subtask_deps_same_project(
            db,
            project_id=task.project_id,
            target_subtask_ids=candidates,
        )
        desired_deps = candidates

        # Milestone-style outlasting rule extended to subtasks (incl. nested):
        #   source.start_date >= target.start_date    (equality allowed)
        #   source.end_date   >  target.end_date      (strict — equality REJECTED)
        if desired_deps:
            target_rows = (
                db.query(
                    SubtaskModel.id, SubtaskModel.name,
                    SubtaskModel.start_date, SubtaskModel.end_date,
                )
                .filter(SubtaskModel.id.in_(desired_deps))
                .all()
            )
            label_index = build_label_index_for_project(db, task.project_id)
            forward = [
                (label_index.label_of(KIND_SUBTASK, tid) or tname, tstart, tend)
                for (tid, tname, tstart, tend) in target_rows
            ]
            starts_v, ends_v = collect_milestone_forward_violations(
                source_start=start_date, source_end=end_date, targets=forward,
            )
            raise_milestone_forward_if_violations(
                starts_v, ends_v,
                source_label=f"Subtask '{name.strip()}'",
                source_start=start_date, source_end=end_date,
                kind_singular="subtask",
            )

    # Status-completion gate: if the caller wants to start the row off
    # as 'completed', every dep target must already be completed too.
    if status == "completed" and desired_deps:
        rows = (
            db.query(SubtaskModel.id, SubtaskModel.name, SubtaskModel.status)
            .filter(SubtaskModel.id.in_(desired_deps))
            .all()
        )
        blockers = [r for r in rows if (r[2] or "") != "completed"]
        if blockers:
            names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
            more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
            raise ValidationError(
                f"Cannot create this subtask as completed — the following "
                f"dependency target(s) are not yet completed: {names}{more}.",
            )

    repo = SubtaskRepository(db)
    # Doc 30 follow-up: auto-bump on position collision (see milestone
    # create service for full rationale). Subtasks have two scopes:
    # nested-under-subtask uses ``parent_subtask_id`` as the
    # uniqueness key; top-level uses ``task_id`` with
    # ``parent_subtask_id IS NULL``.
    if parent_subtask is not None:
        if position is None or repo.position_taken_under_subtask(
            parent_subtask.id, position,
        ):
            pos = repo.next_position_under_subtask(parent_subtask.id)
        else:
            pos = position
    else:
        if position is None or repo.position_taken(task.id, position):
            pos = repo.next_position(task.id)
        else:
            pos = position

    store_mode = resource_mode if type == SUBTASK_TYPE_RESOURCE else None
    store_count = resource_count if (
        type == SUBTASK_TYPE_RESOURCE and resource_mode == RESOURCE_MODE_COUNT
    ) else None

    subtask = repo.create(
        project_id=task.project_id,
        task_id=task.id,
        parent_subtask_id=(parent_subtask.id if parent_subtask is not None else None),
        name=name.strip(),
        description=description,
        type=type,
        start_date=start_date, end_date=end_date,
        actual_start_date=actual_start_date, actual_end_date=actual_end_date,
        position=pos,
        created_by=current_user_id,
        resource_mode=store_mode,
        resource_count=store_count,
        status=status,
        assigned_to=assigned_to,
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

    # Doc 33: subtree audit expansion — record subtask creation on the
    # project's audit log.
    from ...projects.services.audit import ACTION_SUBTASK_CREATE, record_audit
    record_audit(
        db,
        project_id=task.project_id,
        actor_id=current_user_id,
        action=ACTION_SUBTASK_CREATE,
        before=None,
        after={
            "subtask_id": subtask.id,
            "task_id": task.id,
            "parent_subtask_id": (parent_subtask.id if parent_subtask is not None else None),
            "name": subtask.name,
            "type": subtask.type,
            "depends_on": list(desired_deps),
        },
    )
    db.commit()
    refreshed = repo.get_by_id(subtask.id)
    out = refreshed or subtask
    out.depends_on = DependencyRepository(db).list_subtask_dependencies(subtask.id)
    return out, resource_domain
