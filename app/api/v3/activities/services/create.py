"""Create an activity under a milestone. Handles nested resource and dependsOn."""
from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from .....core.errors import NotFoundError, ValidationError
from .....core.project_lock import assert_milestone_activity_writable
from ...projects.services.audit import ACTION_ACTIVITY_CREATE, record_audit
from .....domain.activities.activity import (
    ACTIVITY_STATUS_CHOICES,
    ACTIVITY_STATUS_DEFAULT,
    ACTIVITY_TYPE_RESOURCE,
    ACTIVITY_TYPE_STANDARD,
    Activity,
    RESOURCE_MODE_COUNT,
    RESOURCE_MODE_DETAILS,
)
from .....domain.activities.activity_resource import ActivityResource
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.project import ProjectModel
from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.repositories.activity_repository import ActivityRepository
from .....infrastructure.db.repositories.dependency_repository import (
    DependencyRepository,
)
from .....infrastructure.db.repositories.resource_type_repository import (
    ResourceTypeRepository,
)
from .....shared.date_rules import validate_entity_dates, validate_resource_dates
from .....shared.dep_date_rules import (
    collect_forward_violations,
    raise_forward_if_violations,
)
from .....shared.labels import (
    KIND_ACTIVITY,
    build_label_index_for_project,
    normalize_dependency_inputs,
)


def create_activity(
    db: Session,
    *,
    milestone_id: str,
    name: str,
    description: Optional[str],
    type: Optional[str],
    start_date: datetime,
    end_date: datetime,
    actual_start_date: Optional[datetime],
    actual_end_date: Optional[datetime],
    position: Optional[int],
    resource_mode: Optional[str],
    resource_count: Optional[int],
    resource: Optional[dict],
    current_user_id: Optional[int],
    status: Optional[str] = None,
    depends_on: Optional[List[str]] = None,
    # Doc 38 additions — all optional.
    owner_division: Optional[str] = None,
    concerned_division: Optional[str] = None,
    vendor_id: Optional[str] = None,
) -> Tuple[Activity, Optional[ActivityResource]]:
    milestone = (
        db.query(MilestoneModel)
        .filter(MilestoneModel.id == milestone_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .first()
    )
    if milestone is None:
        raise NotFoundError("The milestone could not be found.")
    assert_milestone_activity_writable(db, milestone.project_id)

    project = db.query(ProjectModel).filter(ProjectModel.id == milestone.project_id).first()
    if project is None or project.start_date is None:
        raise ValidationError(
            "The project this activity belongs to could not be found or has no start date."
        )

    validate_entity_dates(
        entity_start=start_date,
        entity_end=end_date,
        actual_start=actual_start_date,
        actual_end=actual_end_date,
        parent_start_date=milestone.start_date,
        project_start_date=project.start_date,
        entity_label="activity",
        parent_label="milestone",
    )

    # Resource block: validate the classification columns now that we know we
    # have a details-mode resource block.
    if resource is not None:
        validate_resource_dates(
            onboard=resource.get("onboard_date"),
            actual_onboard=resource.get("actual_onboard_date"),
            offboard=resource.get("offboard_date"),
            actual_offboard=resource.get("actual_offboard_date"),
            project_start_date=project.start_date,
        )
        # type_of_resource_id must exist + be active in the catalog.
        type_of_resource_id = resource.get("type_of_resource_id")
        if type_of_resource_id:
            rt_repo = ResourceTypeRepository(db)
            if not rt_repo.is_active(type_of_resource_id):
                raise ValidationError(
                    "The selected 'type of resource' could not be found or is inactive."
                )

    # Normalize: for non-resource activities (or doc-38 type-less rows),
    # mode + count must be NULL.
    is_resource = type == ACTIVITY_TYPE_RESOURCE
    store_mode = resource_mode if is_resource else None
    store_count = resource_count if (
        is_resource and resource_mode == RESOURCE_MODE_COUNT
    ) else None

    # Doc 38: status is no longer accepted on create — it's a PATCH-time
    # field. When the (legacy) caller still supplies a status, validate
    # it against the catalog like before. New rows default to NULL until
    # the user explicitly sets one via PATCH.
    resolved_status: Optional[str] = status
    if resolved_status is not None:
        from .....infrastructure.db.models.activity_status import ActivityStatusModel
        from .....shared.static_catalog import active_codes, is_known_code
        if not is_known_code(
            db, resolved_status,
            model=ActivityStatusModel,
            fallback=ACTIVITY_STATUS_CHOICES,
        ):
            valid = sorted(active_codes(
                db, model=ActivityStatusModel, fallback=ACTIVITY_STATUS_CHOICES,
            ))
            raise ValidationError(
                f"Activity status must be one of: {', '.join(valid)}."
            )

    # Validate dependsOn targets BEFORE creating the row, so we don't leave
    # an orphan activity if validation fails. ``dependsOn`` accepts either
    # UUIDs or display labels (e.g. "A1.2") — see app/shared/labels.py
    # and planned_changes/22.
    desired_deps: List[str] = []
    if depends_on is not None:
        dep_repo = DependencyRepository(db)
        desired_deps = normalize_dependency_inputs(
            db,
            project_id=milestone.project_id,
            expected_kind=KIND_ACTIVITY,
            raw_inputs=depends_on,
            existence_check=dep_repo.existing_target_activity_ids,
        )
        # No cycle / self check needed — the new activity has no id yet, so
        # it can't appear in any existing edge. (Self-edge is impossible on
        # create.) The cycle check kicks in on update.

        # Doc 27: source.start_date >= target.end_date for every dep target.
        if desired_deps:
            target_rows = (
                db.query(
                    ActivityModel.id, ActivityModel.name, ActivityModel.end_date,
                )
                .filter(ActivityModel.id.in_(desired_deps))
                .all()
            )
            label_index = build_label_index_for_project(db, milestone.project_id)
            forward = [
                (label_index.label_of(KIND_ACTIVITY, tid) or tname, tend)
                for (tid, tname, tend) in target_rows
            ]
            raise_forward_if_violations(
                collect_forward_violations(
                    source_start=start_date, targets=forward,
                ),
                source_label=f"Activity '{name.strip()}'",
                source_start=start_date,
            )

    repo = ActivityRepository(db)
    # Doc 30 follow-up: auto-bump on position collision (see milestone
    # create service for full rationale). Caller-supplied position that
    # already exists in the same milestone falls back to next_position.
    if position is None or repo.position_taken(milestone_id, position):
        pos = repo.next_position(milestone_id)
    else:
        pos = position

    activity = repo.create(
        project_id=milestone.project_id,
        milestone_id=milestone_id,
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
        status=resolved_status,
        owner_division=owner_division,
        concerned_division=concerned_division,
        vendor_id=vendor_id,
    )

    resource_domain = None
    # Only create a resource row when we are in details mode.
    if type == ACTIVITY_TYPE_RESOURCE and resource_mode == RESOURCE_MODE_DETAILS:
        resource_domain = repo.insert_resource(
            activity_id=activity.id,
            project_id=milestone.project_id,
            data=resource,
        )

    # Persist dependencies once the activity row exists.
    if desired_deps:
        DependencyRepository(db).set_activity_dependencies(
            activity.id, milestone.project_id, desired_deps,
            actor_id=current_user_id,
        )

    record_audit(
        db,
        project_id=milestone.project_id,
        actor_id=current_user_id,
        action=ACTION_ACTIVITY_CREATE,
        before=None,
        after={
            "activity_id": activity.id,
            "milestone_id": milestone_id,
            "name": activity.name,
            "type": activity.type,
            "start_date": activity.start_date.isoformat() if activity.start_date else None,
            "end_date": activity.end_date.isoformat() if activity.end_date else None,
            "position": activity.position,
            "depends_on": desired_deps,
        },
    )
    db.commit()
    # Re-read so the returned domain model has the freshly-written mode/count.
    refreshed = repo.get_by_id(activity.id)
    out = refreshed or activity
    out.depends_on = DependencyRepository(db).list_activity_dependencies(activity.id)
    return out, resource_domain
