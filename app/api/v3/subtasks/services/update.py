"""Update a subtask. Full type × resource-mode transition matrix + dependsOn.

See activities/services/update.py for the canonical commentary.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_task_subtask_writable
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.subtask import SubtaskModel
from .....infrastructure.db.models.subtask_dependency import SubtaskDependencyModel
from .....infrastructure.db.models.task import TaskModel
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.subtask_repository import SubtaskRepository
from .....shared.date_rules import validate_entity_dates, validate_resource_dates
from .....shared.dep_date_rules import (
    collect_milestone_forward_violations,
    collect_milestone_reverse_violations,
    raise_milestone_forward_if_violations,
    raise_milestone_reverse_if_violations,
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

from .create import _validate_subtask_deps_same_project


_SUBTASK_STATUS_COMPLETED = "completed"


def _gate_subtask_status_against_children(
    db: Session, subtask_id: str, target_status: str,
) -> None:
    """Block flipping a subtask's status to ``completed`` while any
    of its nested subtasks is not yet ``completed``.

    A subtask's children are subtasks attached under it via
    ``parent_subtask_id``. Soft-deleted children are out of scope.
    Only the forward ``completed`` transition is gated.
    """
    if target_status != _SUBTASK_STATUS_COMPLETED:
        return
    rows = (
        db.query(SubtaskModel.id, SubtaskModel.name, SubtaskModel.status)
        .filter(SubtaskModel.parent_subtask_id == subtask_id)
        .filter(SubtaskModel.deleted_at.is_(None))
        .all()
    )
    if not rows:
        return
    blockers = [
        (row[0], row[1], row[2])
        for row in rows
        if (row[2] or "") != _SUBTASK_STATUS_COMPLETED
    ]
    if blockers:
        names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
        more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
        raise ValidationError(
            f"Cannot mark this subtask as completed — the following "
            f"nested subtask{'' if len(blockers) == 1 else 's'} "
            f"{'is' if len(blockers) == 1 else 'are'} not yet completed: "
            f"{names}{more}.",
        )


def _gate_subtask_revert_against_children(
    db: Session, subtask_id: str, target_status: str,
) -> None:
    """Reverse mirror: block flipping the subtask to ``not_completed``
    while any of its nested subtasks is still ``completed``. By induction
    each nested subtask runs the same rule against its own children, so
    the immediate-children check covers the full descendant rollup."""
    if target_status != "not_completed":
        return
    rows = (
        db.query(SubtaskModel.id, SubtaskModel.name, SubtaskModel.status)
        .filter(SubtaskModel.parent_subtask_id == subtask_id)
        .filter(SubtaskModel.deleted_at.is_(None))
        .all()
    )
    if not rows:
        return
    blockers = [
        (row[0], row[1], row[2])
        for row in rows
        if (row[2] or "") == _SUBTASK_STATUS_COMPLETED
    ]
    if blockers:
        names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
        more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
        raise ValidationError(
            f"Cannot revert this subtask to not_completed — the "
            f"following nested subtask"
            f"{' is' if len(blockers) == 1 else 's are'} "
            f"still completed. Revert "
            f"{'it' if len(blockers) == 1 else 'them'} first: "
            f"{names}{more}.",
        )


def update_subtask(
    db: Session,
    *,
    subtask_id: str,
    name: Optional[str],
    description: Optional[str],
    type: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    actual_start_date: Optional[datetime],
    actual_end_date: Optional[datetime],
    position: Optional[int],
    resource_mode: Optional[str],
    resource_count: Optional[int],
    resource: Optional[Dict[str, Any]],
    current_user_id: Optional[int],
    depends_on: Optional[List[str]] = None,
    status: Optional[str] = None,  # doc 38: status now editable on PATCH
    # Doc 41 follow-up: priority code (None = no change).
    priority: Optional[str] = None,
    # Doc 41 follow-up: assignee. Sentinel ``...`` (Ellipsis) = no change;
    # ``None`` = unassign; UUID string = assign. Controller flips between
    # these based on ``data.model_fields_set``.
    assigned_to: Any = ...,
) -> Tuple[Subtask, Optional[SubtaskResource]]:
    repo = SubtaskRepository(db)
    model = repo.get_model(subtask_id)
    if model is None:
        raise NotFoundError("The subtask could not be found.")

    assert_task_subtask_writable(db, model.project_id)

    parent = (
        db.query(TaskModel)
        .filter(TaskModel.id == model.task_id)
        .filter(TaskModel.deleted_at.is_(None))
        .first()
    )
    if parent is None:
        raise NotFoundError(
            "The task this subtask belongs to could not be found. "
            "It may have been deleted."
        )
    project = db.query(ProjectModel).filter(ProjectModel.id == model.project_id).first()
    if project is None or project.start_date is None:
        raise ValidationError(
            "The project this subtask belongs to could not be found or has no start date."
        )

    new_start = start_date if start_date is not None else model.start_date
    new_end = end_date if end_date is not None else model.end_date
    new_actual_start = actual_start_date if actual_start_date is not None else model.actual_start_date
    new_actual_end = actual_end_date if actual_end_date is not None else model.actual_end_date

    validate_entity_dates(
        entity_start=new_start, entity_end=new_end,
        actual_start=new_actual_start, actual_end=new_actual_end,
        parent_start_date=parent.start_date, project_start_date=project.start_date,
        entity_label="subtask",
        parent_label="task",
    )

    new_type = type if type is not None else model.type
    new_mode = resource_mode if resource_mode is not None else model.resource_mode
    new_count = resource_count if resource_count is not None else model.resource_count

    if new_type != SUBTASK_TYPE_RESOURCE:
        if resource_mode is not None:
            raise ValidationError(
                "Resource mode should only be provided when the subtask type is 'resource'."
            )
        if resource_count is not None:
            raise ValidationError(
                "Resource count should only be provided when the subtask type is 'resource'."
            )
        if resource is not None:
            raise ValidationError(
                "Resource details should only be provided when the subtask type is 'resource'."
            )
        final_mode = None
        final_count = None
        target_has_resource_row = False
    else:
        if new_mode is None:
            raise ValidationError(
                "Please choose a resource mode ('count' or 'details') for a Resource-type subtask."
            )
        if new_mode == RESOURCE_MODE_COUNT:
            if new_count is None:
                raise ValidationError("Resource count is required when resource mode is 'count'.")
            if resource is not None:
                raise ValidationError("Resource details should be omitted when resource mode is 'count'.")
            final_mode = RESOURCE_MODE_COUNT
            final_count = new_count
            target_has_resource_row = False
        else:
            had_live_resource = repo.get_live_resource(subtask_id) is not None
            if not had_live_resource and resource is None:
                raise ValidationError(
                    "Please provide the resource details when using resource mode 'details'."
                )
            if resource_count is not None:
                raise ValidationError("Resource count should be omitted when resource mode is 'details'.")
            final_mode = RESOURCE_MODE_DETAILS
            final_count = None
            target_has_resource_row = True

    if resource is not None:
        validate_resource_dates(
            onboard=resource.get("onboard_date"),
            actual_onboard=resource.get("actual_onboard_date"),
            offboard=resource.get("offboard_date"),
            actual_offboard=resource.get("actual_offboard_date"),
            project_start_date=project.start_date,
        )

    desired_deps: Optional[List[str]] = None
    if depends_on is not None:
        candidates, _id_to_raw = resolve_labels_to_ids(
            db,
            project_id=model.project_id,
            expected_kind=KIND_SUBTASK,
            raw_inputs=depends_on,
        )
        if subtask_id in candidates:
            raise ValidationError("A subtask cannot depend on itself.")
        if candidates:
            _validate_subtask_deps_same_project(
                db,
                project_id=model.project_id,
                target_subtask_ids=candidates,
            )
            cycler = DependencyRepository(db).would_create_cycle_subtask(
                subtask_id, candidates,
            )
            if cycler is not None:
                raise ValidationError(
                    f"Adding dependency on '{cycler}' would create a cycle."
                )
        desired_deps = candidates

    # Doc 27: cross-dependency date enforcement.
    effective_start = start_date if start_date is not None else model.start_date
    effective_end = end_date if end_date is not None else model.end_date
    label_index = None
    forward_targets_to_check: List[str]
    if desired_deps is not None:
        forward_targets_to_check = desired_deps
    elif start_date is not None:
        forward_targets_to_check = DependencyRepository(db) \
            .list_subtask_dependencies(subtask_id)
    else:
        forward_targets_to_check = []
    if forward_targets_to_check and (effective_start is not None or effective_end is not None):
        target_rows = (
            db.query(
                SubtaskModel.id, SubtaskModel.name,
                SubtaskModel.start_date, SubtaskModel.end_date,
            )
            .filter(SubtaskModel.id.in_(forward_targets_to_check))
            .all()
        )
        if label_index is None:
            label_index = build_label_index_for_project(db, model.project_id)
        forward = [
            (label_index.label_of(KIND_SUBTASK, tid) or tname, tstart, tend)
            for (tid, tname, tstart, tend) in target_rows
        ]
        starts_v, ends_v = collect_milestone_forward_violations(
            source_start=effective_start, source_end=effective_end, targets=forward,
        )
        raise_milestone_forward_if_violations(
            starts_v, ends_v,
            source_label=(
                f"Subtask '{label_index.label_of(KIND_SUBTASK, subtask_id) or model.name}'"
            ),
            source_start=effective_start, source_end=effective_end,
            kind_singular="subtask",
        )
    if (start_date is not None or end_date is not None) and (
        effective_start is not None or effective_end is not None
    ):
        sources = (
            db.query(
                SubtaskModel.id, SubtaskModel.name,
                SubtaskModel.start_date, SubtaskModel.end_date,
            )
            .join(
                SubtaskDependencyModel,
                SubtaskDependencyModel.source_subtask_id == SubtaskModel.id,
            )
            .filter(SubtaskDependencyModel.target_subtask_id == subtask_id)
            .filter(SubtaskDependencyModel.deleted_at.is_(None))
            .filter(SubtaskModel.deleted_at.is_(None))
            .all()
        )
        if sources:
            if label_index is None:
                label_index = build_label_index_for_project(db, model.project_id)
            rev = [
                (label_index.label_of(KIND_SUBTASK, sid) or sname, sstart, send)
                for (sid, sname, sstart, send) in sources
            ]
            starts_v, ends_v = collect_milestone_reverse_violations(
                target_start=effective_start, target_end=effective_end, sources=rev,
            )
            raise_milestone_reverse_if_violations(
                starts_v, ends_v,
                target_label=(
                    f"Subtask '{label_index.label_of(KIND_SUBTASK, subtask_id) or model.name}'"
                ),
                target_start=effective_start, target_end=effective_end,
                kind_singular="subtask",
            )

    # Children-completion gate: a subtask may only flip to
    # ``completed`` when every nested subtask under it is also
    # ``completed``. Recursive depth is handled by induction —
    # each nested subtask runs the same gate against its own
    # children at flip time.
    if status is not None:
        _gate_subtask_status_against_children(db, subtask_id, status)
        # Reverse mirror — block reverting to ``not_completed`` while
        # any nested subtask is still ``completed``.
        _gate_subtask_revert_against_children(db, subtask_id, status)

    # Doc 41 follow-up: priority — when supplied, must be an active code
    # in the priorities catalog. None = no change. Independent per-level.
    if priority is not None:
        from .....infrastructure.db.models.priority import PriorityModel
        from .....shared.static_catalog import is_known_code, active_codes
        from .....domain.priorities.priority import PRIORITY_CHOICES
        if not is_known_code(
            db, priority, model=PriorityModel, fallback=PRIORITY_CHOICES,
        ):
            valid = sorted(active_codes(
                db, model=PriorityModel, fallback=PRIORITY_CHOICES,
            ))
            raise ValidationError(
                f"Priority must be one of: {', '.join(valid)}."
            )

    # Doc 41 follow-up: assignee — only validate / write when explicitly
    # sent (sentinel != ...). UUID -> validate; None -> just clear.
    if assigned_to is not ...:
        if assigned_to is not None:
            from .....shared.assignee import validate_assignable_user_id
            validate_assignable_user_id(db, assigned_to)

    updates: Dict[str, Any] = {}
    if name is not None: updates["name"] = name.strip()
    if description is not None: updates["description"] = description
    if type is not None: updates["type"] = new_type
    if start_date is not None: updates["start_date"] = start_date
    if end_date is not None: updates["end_date"] = end_date
    if actual_start_date is not None: updates["actual_start_date"] = actual_start_date
    if actual_end_date is not None: updates["actual_end_date"] = actual_end_date
    if position is not None: updates["position"] = position
    if status is not None: updates["status"] = status  # doc 38
    if priority is not None: updates["priority"] = priority
    if assigned_to is not ...: updates["assigned_to"] = assigned_to
    if final_mode != model.resource_mode or final_count != model.resource_count:
        updates["resource_mode"] = final_mode
        updates["resource_count"] = final_count

    if updates:
        repo.update(subtask_id, updates=updates, updated_by=current_user_id)

    resource_domain: Optional[SubtaskResource] = None
    if target_has_resource_row:
        if resource is not None:
            resource_domain = repo.upsert_resource(
                subtask_id=subtask_id, project_id=model.project_id, data=resource,
            )
        else:
            resource_domain = repo.get_live_resource(subtask_id)
    else:
        repo.soft_delete_live_resource(subtask_id)
        resource_domain = None

    if desired_deps is not None:
        DependencyRepository(db).set_subtask_dependencies(
            subtask_id, model.project_id, desired_deps,
            actor_id=current_user_id,
        )

    db.commit()
    updated = repo.get_by_id(subtask_id)
    assert updated is not None
    updated.depends_on = DependencyRepository(db).list_subtask_dependencies(subtask_id)
    return updated, resource_domain
