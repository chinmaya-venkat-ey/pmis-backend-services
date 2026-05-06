"""
Update an activity.

Handles the full type × resource-mode transition matrix in one place plus the
new ``depends_on`` and the status-completion gate.

Status gate
-----------
Per the dependency spec, an activity may only flip ``status`` to
``completed`` once every activity it ``depends_on`` is also ``completed``.
Direct status check (no recursive children rollup); fast and predictable.

Depends-on
----------
Replace-list semantics:
  None (omitted)  → leave list unchanged
  []              → clear all edges
  [ids...]        → replace; targets validated for existence in same project,
                    no self-edge, no cycle.

All changes commit in a single transaction.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .....core.errors import (
    NotFoundError,
    ValidationError,
)
from .....core.project_lock import assert_milestone_activity_writable
from ...projects.services.audit import (
    ACTION_ACTIVITY_DEP_CHANGE,
    ACTION_ACTIVITY_UPDATE,
    record_audit,
)


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.repositories.activity_repository import ActivityRepository
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....shared.labels import (
    KIND_ACTIVITY,
    build_label_index_for_project,
    normalize_dependency_inputs,
)
from .....infrastructure.db.repositories.resource_type_repository import (
    ResourceTypeRepository,
)
from .....shared.date_rules import validate_entity_dates, validate_resource_dates
from .....shared.dep_date_rules import (
    collect_forward_violations,
    collect_reverse_violations,
    raise_forward_if_violations,
    raise_reverse_if_violations,
)
from .....infrastructure.db.models.activity_dependency import (
    ActivityDependencyModel,
)
from .....domain.activities.activity import (
    Activity,
    ACTIVITY_STATUS_CHOICES,
    ACTIVITY_STATUS_COMPLETED,
    ACTIVITY_STATUS_DEFAULT,
    ACTIVITY_TYPE_RESOURCE,
    ACTIVITY_TYPE_STANDARD,
    RESOURCE_MODE_COUNT,
    RESOURCE_MODE_DETAILS,
)
from .....domain.activities.activity_resource import ActivityResource


def _gate_status_against_deps(
    db: Session, activity_id: str, target_status: str,
) -> None:
    """Raise ValidationError if any dep target is not 'completed'.

    Only invoked when the new status is ``completed``. Reads the current edge
    set from activity_dependencies, then checks each target's status column.
    """
    if target_status != ACTIVITY_STATUS_COMPLETED:
        return
    dep_repo = DependencyRepository(db)
    target_ids = dep_repo.list_activity_dependencies(activity_id)
    if not target_ids:
        return
    rows = (
        db.query(ActivityModel.id, ActivityModel.name, ActivityModel.status)
        .filter(ActivityModel.id.in_(target_ids))
        .all()
    )
    blockers = [
        (row[0], row[1], row[2])
        for row in rows
        if (row[2] or "") != ACTIVITY_STATUS_COMPLETED
    ]
    if blockers:
        names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
        more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
        raise ValidationError(
            f"Cannot mark this activity as completed — the following "
            f"dependency target(s) are not yet completed: {names}{more}.",
        )


def update_activity(
    db: Session,
    *,
    activity_id: str,
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
    status: Optional[str] = None,
    depends_on: Optional[List[str]] = None,
) -> Tuple[Activity, Optional[ActivityResource]]:
    repo = ActivityRepository(db)
    model = repo.get_model(activity_id)
    if model is None:
        raise NotFoundError("The activity could not be found.")

    assert_milestone_activity_writable(db, model.project_id)

    milestone = (
        db.query(MilestoneModel)
        .filter(MilestoneModel.id == model.milestone_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .first()
    )
    if milestone is None:
        raise NotFoundError(
            "The milestone this activity belongs to could not be found. "
            "It may have been deleted."
        )
    project = db.query(ProjectModel).filter(ProjectModel.id == model.project_id).first()
    if project is None or project.start_date is None:
        raise ValidationError(
            "The project this activity belongs to could not be found or has no start date."
        )

    # Merge incoming partial values against current state for date checks.
    new_start = start_date if start_date is not None else model.start_date
    new_end = end_date if end_date is not None else model.end_date
    new_actual_start = actual_start_date if actual_start_date is not None else model.actual_start_date
    new_actual_end = actual_end_date if actual_end_date is not None else model.actual_end_date

    validate_entity_dates(
        entity_start=new_start,
        entity_end=new_end,
        actual_start=new_actual_start,
        actual_end=new_actual_end,
        parent_start_date=milestone.start_date,
        project_start_date=project.start_date,
        entity_label="activity",
        parent_label="milestone",
    )

    # Determine the FINAL (type, mode, count, has_resource_body) shape after
    # applying this partial update.
    new_type = type if type is not None else model.type
    # resource_mode follows the same "None = unchanged" semantic as type.
    new_mode = resource_mode if resource_mode is not None else model.resource_mode
    # resource_count follows the same pattern.
    new_count = resource_count if resource_count is not None else model.resource_count

    # Validate final shape based on new_type.
    if new_type != ACTIVITY_TYPE_RESOURCE:
        # Non-resource activity: mode and count will be cleared, resource row
        # soft-deleted. Reject body fields that wouldn't make sense.
        if resource_mode is not None:
            raise ValidationError(
                "Resource mode should only be provided when the activity type is 'resource'."
            )
        if resource_count is not None:
            raise ValidationError(
                "Resource count should only be provided when the activity type is 'resource'."
            )
        if resource is not None:
            raise ValidationError(
                "Resource details should only be provided when the activity type is 'resource'."
            )
        final_mode = None
        final_count = None
        target_has_resource_row = False
    else:
        # Resource activity -- we need a concrete final mode.
        if new_mode is None:
            raise ValidationError(
                "Please choose a resource mode ('count' or 'details') for a Resource-type activity."
            )
        if new_mode == RESOURCE_MODE_COUNT:
            if new_count is None:
                raise ValidationError(
                    "Resource count is required when resource mode is 'count'."
                )
            if resource is not None:
                raise ValidationError(
                    "Resource details should be omitted when resource mode is 'count'."
                )
            final_mode = RESOURCE_MODE_COUNT
            final_count = new_count
            target_has_resource_row = False
        else:  # details
            # Switching to (or staying in) details: body may provide a resource
            # block. If not provided, a live one must already exist.
            had_live_resource = repo.get_live_resource(activity_id) is not None
            if not had_live_resource and resource is None:
                raise ValidationError(
                    "Please provide the resource details when using resource mode 'details'."
                )
            # Reject only if the CALLER explicitly sent resource_count in the body.
            # A stale value inherited from prior 'count' mode is silently cleared.
            if resource_count is not None:
                raise ValidationError(
                    "Resource count should be omitted when resource mode is 'details'."
                )
            final_mode = RESOURCE_MODE_DETAILS
            final_count = None
            target_has_resource_row = True

    # Validate resource dates if a resource block was provided.
    if resource is not None:
        validate_resource_dates(
            onboard=resource.get("onboard_date"),
            actual_onboard=resource.get("actual_onboard_date"),
            offboard=resource.get("offboard_date"),
            actual_offboard=resource.get("actual_offboard_date"),
            project_start_date=project.start_date,
        )
        # Validate type_of_resource_id existence when provided.
        new_type_of_resource_id = resource.get("type_of_resource_id")
        if new_type_of_resource_id is not None:
            rt_repo = ResourceTypeRepository(db)
            if not rt_repo.is_active(new_type_of_resource_id):
                raise ValidationError(
                    "The selected 'type of resource' could not be found or is inactive."
                )

    # Lifecycle status: applies to all activity types. The schema-level
    # validator (in ActivityUpdateRequest) already enforces value-membership
    # for any non-None input; we keep the service-layer guard so direct
    # callers (CLI, internal scripts) can't bypass the choices.
    status_supplied = status is not None
    if status_supplied:
        # Doc 37 part 1: catalog-first; fallback to in-code tuple.
        from .....infrastructure.db.models.activity_status import (
            ActivityStatusModel,
        )
        from .....shared.static_catalog import active_codes, is_known_code
        if not is_known_code(
            db, status,
            model=ActivityStatusModel,
            fallback=ACTIVITY_STATUS_CHOICES,
        ):
            valid = sorted(active_codes(
                db, model=ActivityStatusModel,
                fallback=ACTIVITY_STATUS_CHOICES,
            ))
            raise ValidationError(
                f"Activity status must be one of: {', '.join(valid)}."
            )

    # Status-completion gate. Only run when the caller is explicitly trying
    # to set status to 'completed'.
    if status_supplied and status == ACTIVITY_STATUS_COMPLETED:
        # Use the eventual edge set if depends_on is being replaced this PATCH;
        # otherwise the existing set.
        if depends_on is not None:
            # Build a temporary lookup against the would-be targets.
            # Only "would-be" targets need to be validated against status.
            target_ids = [d for d in dict.fromkeys(depends_on) if d]
            if target_ids:
                rows = (
                    db.query(ActivityModel.id, ActivityModel.name, ActivityModel.status)
                    .filter(ActivityModel.id.in_(target_ids))
                    .all()
                )
                blockers = [
                    (r[0], r[1], r[2]) for r in rows
                    if (r[2] or "") != ACTIVITY_STATUS_COMPLETED
                ]
                if blockers:
                    names = ", ".join(f"'{b[1]}'" for b in blockers[:3])
                    more = "" if len(blockers) <= 3 else f" (+{len(blockers) - 3} more)"
                    raise AuthorizationError(
                        f"Cannot mark this activity as completed — the "
                        f"following dependency target(s) are not yet "
                        f"completed: {names}{more}.",
                    )
        else:
            _gate_status_against_deps(db, activity_id, ACTIVITY_STATUS_COMPLETED)

    # Validate dependsOn targets for replace. Accepts UUIDs or labels
    # (e.g. "A1.2"); see app/shared/labels.py and planned_changes/22.
    desired_deps: Optional[List[str]] = None
    if depends_on is not None:
        dep_repo = DependencyRepository(db)
        candidates = normalize_dependency_inputs(
            db,
            project_id=model.project_id,
            expected_kind=KIND_ACTIVITY,
            raw_inputs=depends_on,
            existence_check=dep_repo.existing_target_activity_ids,
        )
        # Self-edge guard. Done AFTER normalization because a label like
        # "A1.2" can resolve to the source's own UUID.
        if activity_id in candidates:
            raise ValidationError(
                "An activity cannot depend on itself."
            )
        if candidates:
            # Cycle detection: would adding any of these create a cycle?
            # Check against existing edges that don't include the source's
            # current outgoing set (those will be replaced below).
            cycler = dep_repo.would_create_cycle_activity(activity_id, candidates)
            if cycler is not None:
                raise ValidationError(
                    f"Adding dependency on '{cycler}' would create a cycle."
                )
        desired_deps = candidates

    # Doc 27: cross-dependency date enforcement.
    # Compute the activity's effective post-edit dates first.
    effective_start = start_date if start_date is not None else model.start_date
    effective_end = end_date if end_date is not None else model.end_date
    label_index = None  # built lazily; only when we need labels
    # Forward: validate this activity's effective start_date against the
    # eventual outgoing dep target set (new if replacing, existing otherwise).
    forward_targets_to_check: List[str]
    if desired_deps is not None:
        forward_targets_to_check = desired_deps
    elif start_date is not None:
        # depends_on unchanged but start_date moved — re-check existing edges.
        forward_targets_to_check = DependencyRepository(db) \
            .list_activity_dependencies(activity_id)
    else:
        forward_targets_to_check = []
    if forward_targets_to_check and effective_start is not None:
        target_rows = (
            db.query(ActivityModel.id, ActivityModel.name, ActivityModel.end_date)
            .filter(ActivityModel.id.in_(forward_targets_to_check))
            .all()
        )
        if label_index is None:
            label_index = build_label_index_for_project(db, model.project_id)
        forward = [
            (label_index.label_of(KIND_ACTIVITY, tid) or tname, tend)
            for (tid, tname, tend) in target_rows
        ]
        raise_forward_if_violations(
            collect_forward_violations(
                source_start=effective_start, targets=forward,
            ),
            source_label=(
                f"Activity '{label_index.label_of(KIND_ACTIVITY, activity_id) or model.name}'"
            ),
            source_start=effective_start,
        )
    # Reverse: if end_date is moving, walk the live sources pointing at me
    # and reject if the new end_date would make any of them start too early.
    if end_date is not None and effective_end is not None:
        sources = (
            db.query(ActivityModel.id, ActivityModel.name, ActivityModel.start_date)
            .join(
                ActivityDependencyModel,
                ActivityDependencyModel.source_activity_id == ActivityModel.id,
            )
            .filter(ActivityDependencyModel.target_activity_id == activity_id)
            .filter(ActivityDependencyModel.deleted_at.is_(None))
            .filter(ActivityModel.deleted_at.is_(None))
            .all()
        )
        if sources:
            if label_index is None:
                label_index = build_label_index_for_project(db, model.project_id)
            rev = [
                (label_index.label_of(KIND_ACTIVITY, sid) or sname, sstart)
                for (sid, sname, sstart) in sources
            ]
            raise_reverse_if_violations(
                collect_reverse_violations(
                    target_end=effective_end, sources=rev,
                ),
                target_label=(
                    f"Activity '{label_index.label_of(KIND_ACTIVITY, activity_id) or model.name}'"
                ),
                target_end=effective_end,
            )

    # Build the activity-row update dict.
    updates: Dict[str, Any] = {}
    if name is not None:
        updates["name"] = name.strip()
    if description is not None:
        updates["description"] = description
    if type is not None:
        updates["type"] = new_type
    if start_date is not None:
        updates["start_date"] = start_date
    if end_date is not None:
        updates["end_date"] = end_date
    if actual_start_date is not None:
        updates["actual_start_date"] = actual_start_date
    if actual_end_date is not None:
        updates["actual_end_date"] = actual_end_date
    if position is not None:
        updates["position"] = position
    # Always write the resolved final_mode / final_count so transitions clean up.
    # These may flip values to/from NULL.
    if final_mode != model.resource_mode or final_count != model.resource_count:
        updates["resource_mode"] = final_mode
        updates["resource_count"] = final_count

    # Status: write whatever the caller supplied. Type changes do NOT
    # clear status anymore — every activity type carries a lifecycle
    # state, so preserving it across type transitions is correct
    # (an activity that was already 'completed' as a resource activity
    # stays 'completed' if its type flips to standard).
    if status_supplied:
        updates["status"] = status

    before_snapshot = {k: _iso(getattr(model, k)) for k in updates.keys()} if updates else {}

    if updates:
        repo.update(activity_id, updates=updates, updated_by=current_user_id)

    # Reconcile the resource sub-entity.
    resource_domain: Optional[ActivityResource] = None
    if target_has_resource_row:
        # details mode: upsert if body provided; otherwise leave existing row.
        if resource is not None:
            resource_domain = repo.upsert_resource(
                activity_id=activity_id,
                project_id=model.project_id,
                data=resource,
            )
        else:
            resource_domain = repo.get_live_resource(activity_id)
    else:
        # count or non-resource: any live resource row must be soft-deleted.
        repo.soft_delete_live_resource(activity_id)
        resource_domain = None

    # Apply dependsOn replace AFTER the row update so cycle/state checks
    # used the pre-replace edge set (which we wanted).
    if desired_deps is not None:
        DependencyRepository(db).set_activity_dependencies(
            activity_id, model.project_id, desired_deps,
            actor_id=current_user_id,
        )

    if updates or desired_deps is not None:
        record_audit(
            db,
            project_id=model.project_id,
            actor_id=current_user_id,
            action=ACTION_ACTIVITY_UPDATE,
            before={"activity_id": activity_id, **before_snapshot},
            after={k: _iso(v) for k, v in updates.items()},
        )

    if desired_deps is not None:
        # Doc 33: dep-edge changes get their own audit row.
        record_audit(
            db,
            project_id=model.project_id,
            actor_id=current_user_id,
            action=ACTION_ACTIVITY_DEP_CHANGE,
            before={"activity_id": activity_id},
            after={"activity_id": activity_id, "depends_on": list(desired_deps)},
        )

    db.commit()

    updated = repo.get_by_id(activity_id)
    assert updated is not None
    updated.depends_on = DependencyRepository(db).list_activity_dependencies(activity_id)
    return updated, resource_domain
