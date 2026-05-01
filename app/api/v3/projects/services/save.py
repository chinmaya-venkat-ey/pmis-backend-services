"""
Finalize Step-1 project setup.

Maps to the mockup's **Save Project** button: once the user has added at
least one milestone, clicking Save flips the project from ``new`` to
``draft``. Adding a milestone alone does not change status — the trigger is
the explicit Save action (this endpoint).

Idempotent: calling Save on a project already past ``new`` is a no-op that
returns the project unchanged with HTTP 200.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .....infrastructure.db.models.milestone import MilestoneModel
from .....infrastructure.db.repositories.project_repository import ProjectRepository
from .....shared.service_result import ServiceResult

from .audit import ACTION_DRAFT, project_snapshot, record_audit
from .transitions import STATUS_NEW, transition_to_draft_if_new


def save_project_setup(
    db: Session,
    project_id: str,
    *,
    actor_id: Optional[int],
) -> ServiceResult:
    """
    Apply the ``Save Project`` action.

    - 404 if the project does not exist (or is soft-deleted).
    - 422 if the project is still ``new`` and has no live milestone yet
      (the Save button should be disabled in this state on the frontend).
    - 200 no-op when called on a project already past ``new``.
    - 200 with ``status='draft'`` on the first successful call.
    """
    repo = ProjectRepository(db)
    project = repo.get_by_id(project_id)
    if project is None:
        return ServiceResult.fail(
            error=f"Project with ID {project_id} not found",
            error_type="not_found",
        )

    # Idempotency: Save is a no-op once the project has moved past 'new'.
    # No audit row, no write. The frontend is free to call this on every
    # click of the Save button.
    if (project.status or "").lower() != STATUS_NEW:
        return ServiceResult.ok(project)

    # Guard: the team-lead UX requires at least one live milestone to exist
    # before the Save button flips status. The button is disabled on the
    # frontend in this case; this check is the server-side mirror.
    has_milestone = (
        db.query(MilestoneModel.id)
        .filter(
            MilestoneModel.project_id == project_id,
            MilestoneModel.deleted_at.is_(None),
        )
        .first()
        is not None
    )
    if not has_milestone:
        return ServiceResult.fail(
            error="Add at least one milestone before saving the project.",
            error_type="validation_error",
        )

    before = project_snapshot(project)

    try:
        updated = transition_to_draft_if_new(db, project_id, actor_id)
        if updated is None:
            # Should not happen given the status check above, but treat as a
            # no-op rather than an error.
            return ServiceResult.ok(project)

        record_audit(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action=ACTION_DRAFT,
            before=before,
            after=project_snapshot(updated),
        )
        db.commit()
        return ServiceResult.ok(updated)

    except Exception as e:
        db.rollback()
        return ServiceResult.fail(
            error=f"Failed to save project: {str(e)}",
            error_type="internal_error",
        )
