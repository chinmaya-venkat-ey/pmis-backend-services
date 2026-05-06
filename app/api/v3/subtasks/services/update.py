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
    collect_forward_violations,
    collect_reverse_violations,
    raise_forward_if_violations,
    raise_reverse_if_violations,
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
    if forward_targets_to_check and effective_start is not None:
        target_rows = (
            db.query(SubtaskModel.id, SubtaskModel.name, SubtaskModel.end_date)
            .filter(SubtaskModel.id.in_(forward_targets_to_check))
            .all()
        )
        if label_index is None:
            label_index = build_label_index_for_project(db, model.project_id)
        forward = [
            (label_index.label_of(KIND_SUBTASK, tid) or tname, tend)
            for (tid, tname, tend) in target_rows
        ]
        raise_forward_if_violations(
            collect_forward_violations(
                source_start=effective_start, targets=forward,
            ),
            source_label=(
                f"Subtask '{label_index.label_of(KIND_SUBTASK, subtask_id) or model.name}'"
            ),
            source_start=effective_start,
        )
    if end_date is not None and effective_end is not None:
        sources = (
            db.query(SubtaskModel.id, SubtaskModel.name, SubtaskModel.start_date)
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
                (label_index.label_of(KIND_SUBTASK, sid) or sname, sstart)
                for (sid, sname, sstart) in sources
            ]
            raise_reverse_if_violations(
                collect_reverse_violations(
                    target_end=effective_end, sources=rev,
                ),
                target_label=(
                    f"Subtask '{label_index.label_of(KIND_SUBTASK, subtask_id) or model.name}'"
                ),
                target_end=effective_end,
            )

    updates: Dict[str, Any] = {}
    if name is not None: updates["name"] = name.strip()
    if description is not None: updates["description"] = description
    if type is not None: updates["type"] = new_type
    if start_date is not None: updates["start_date"] = start_date
    if end_date is not None: updates["end_date"] = end_date
    if actual_start_date is not None: updates["actual_start_date"] = actual_start_date
    if actual_end_date is not None: updates["actual_end_date"] = actual_end_date
    if position is not None: updates["position"] = position
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
