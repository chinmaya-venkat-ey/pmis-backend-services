"""
Publish a project (new|draft -> published).

Admin-only at the endpoint layer. The transition rules in
``transitions`` reject anything illegal.

Doc 27: structural completeness gate. Before flipping status to
``published`` we reject if (a) the project has zero live milestones, or
(b) any live milestone has zero live activities.
"""
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from .....core.errors import ValidationError
from .....domain.projects.project import Project
from .....infrastructure.db.models.activity import ActivityModel
from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....shared.service_result import ServiceResult

from .audit import ACTION_PUBLISH, project_snapshot, record_audit
from .transitions import STATUS_PUBLISHED, assert_transition_allowed


def _milestones_without_activities(
    db: Session, project_id: str,
) -> List[Tuple[str, str]]:
    """Return [(milestone_id, milestone_name), ...] for live milestones in
    this project that have zero live activities. Sorted by position then
    name for stable ordering in the error message."""
    rows = (
        db.query(MilestoneModel.id, MilestoneModel.name, MilestoneModel.position)
        .outerjoin(
            ActivityModel,
            (ActivityModel.milestone_id == MilestoneModel.id)
            & (ActivityModel.deleted_at.is_(None)),
        )
        .filter(MilestoneModel.project_id == project_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .group_by(MilestoneModel.id, MilestoneModel.name, MilestoneModel.position)
        .having(func.count(ActivityModel.id) == 0)
        .all()
    )
    rows_sorted = sorted(rows, key=lambda r: (r[2] if r[2] is not None else 0, r[1] or ""))
    return [(r[0], r[1]) for r in rows_sorted]


def _live_milestone_count(db: Session, project_id: str) -> int:
    return (
        db.query(MilestoneModel.id)
        .filter(MilestoneModel.project_id == project_id)
        .filter(MilestoneModel.deleted_at.is_(None))
        .count()
    )


def publish_project(
    db: Session,
    project_id: str,
    *,
    actor_id: Optional[str],
    actor_is_admin: bool,
) -> ServiceResult[Project]:
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if project is None:
        return ServiceResult.fail(
            error=f"Project with ID {project_id} not found",
            error_type="not_found",
        )

    if (project.status or "").lower() == STATUS_PUBLISHED:
        return ServiceResult.fail(
            error="Project is already published",
            error_type="invalid_transition",
            details={"errorIdentifier": "invalid_transition", "from": project.status, "to": STATUS_PUBLISHED},
        )

    try:
        assert_transition_allowed(
            from_status=project.status,
            to_status=STATUS_PUBLISHED,
            actor_is_admin=actor_is_admin,
            db=db,
        )
    except ValidationError as e:
        return ServiceResult.fail(
            error=e.message,
            error_type=e.details.get("errorIdentifier", "invalid_transition"),
            details=e.details,
        )

    # Doc 27: structural-completeness gates — must have at least one
    # milestone, and every milestone must carry at least one activity.
    if _live_milestone_count(db, project_id) == 0:
        return ServiceResult.fail(
            error=(
                "Cannot publish: the project has no milestones. Add at "
                "least one milestone with one activity before publishing."
            ),
            error_type="invalid_publish",
            details={"errorIdentifier": "no_milestones"},
        )
    empties = _milestones_without_activities(db, project_id)
    if empties:
        names = ", ".join(f"'{n}'" for _, n in empties)
        return ServiceResult.fail(
            error=(
                f"Cannot publish: the following milestone(s) have no "
                f"activities: {names}. Add at least one activity to each, "
                f"or delete the empty milestone."
            ),
            error_type="invalid_publish",
            details={
                "errorIdentifier": "milestone_without_activity",
                "milestoneIds": [mid for mid, _ in empties],
                "milestoneNames": [n for _, n in empties],
            },
        )

    before = project_snapshot(project)

    try:
        updated = repo.update(
            project_id=project_id,
            status=STATUS_PUBLISHED,
            updated_by=actor_id,
        )
        if updated is None:
            return ServiceResult.fail(
                error=f"Project with ID {project_id} not found",
                error_type="not_found",
            )

        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action=ACTION_PUBLISH,
            before=before,
            after=project_snapshot(updated),
        )

        db.commit()
        return ServiceResult.ok(updated)

    except Exception as e:
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to publish project: {str(e)}",
            error_type="internal_error",
        )
