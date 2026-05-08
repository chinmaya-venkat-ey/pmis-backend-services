"""
Shared write-lock helpers for milestones / activities / tasks / subtasks.

Every write path in those modules calls one of these guards before mutating
anything, so the rule for "can this project accept this kind of write right
now?" lives in one place.

Lifecycle gates (post-doc-35 follow-up: tasks + subtasks are publish-gated)
--------------------------------------------------------------------------
- Milestones / activities are writable any time the project is live (i.e.
  exists and is not soft-deleted). They're how the user assembles the
  baseline that's later signed off by publishing.

- Tasks / subtasks are writable ONLY while the project's status is
  ``published``. A user must add the milestones + activities, satisfy the
  doc 27 publish gate ("≥1 milestone, every milestone has ≥1 activity"),
  publish the project, and only then add tasks / subtasks. Reverting a
  published project to draft locks T/S writes again until the next
  publish.

  Rationale: tasks and subtasks are execution-detail rows; the design
  intent is that they can only exist on a project that's been formally
  published once. Captured by the senior in the post-doc-33 review.

Functions
---------
- ``assert_project_editable`` — project exists and is not soft-deleted.
- ``assert_milestone_activity_writable`` — same as above, kept distinct
  so the M/A code paths read clearly.
- ``assert_task_subtask_writable`` — project exists, not soft-deleted,
  AND status is ``published``. Raises ``ValidationError`` (HTTP 422)
  when the status gate fails.
"""
from sqlalchemy.orm import Session

from ..infrastructure.db.models.project import ProjectModel
from .errors import NotFoundError, ValidationError


# Project status that unlocks task / subtask writes. Mirrors the
# constant in ``app.api.v3.projects.services.transitions`` but kept
# inline here so this module doesn't import the projects service layer
# (would create a cycle).
_STATUS_PUBLISHED = "published"


def _load_live_project(db: Session, project_id: str) -> ProjectModel:
    """Fetch a project and raise NotFoundError if missing or soft-deleted."""
    project = (
        db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    )
    if project is None:
        raise NotFoundError("The project could not be found.")
    if getattr(project, "deleted_at", None) is not None:
        raise NotFoundError(
            "The project has been deleted and cannot be edited."
        )
    return project


def assert_project_editable(db: Session, project_id: str) -> None:
    """Project exists and is not soft-deleted."""
    _load_live_project(db, project_id)


def assert_milestone_activity_writable(db: Session, project_id: str) -> None:
    """Project accepts milestone / activity writes (any non-deleted state)."""
    _load_live_project(db, project_id)


def assert_task_subtask_writable(db: Session, project_id: str) -> None:
    """Project accepts task / subtask writes.

    Requires the project to be live AND in ``published`` status. A
    project in ``new`` / ``draft`` / ``closed`` returns a 422
    validation error with a clear message — the FE shows it as "publish
    the project before adding tasks / subtasks".
    """
    project = _load_live_project(db, project_id)
    status = (getattr(project, "status", None) or "").lower()
    if status != _STATUS_PUBLISHED:
        raise ValidationError(
            "Tasks and subtasks can only be added to a published project. "
            "Publish the project first.",
            details={
                "errorIdentifier": "publish_required",
                "projectId": project_id,
                "projectStatus": status,
                "requiredStatus": _STATUS_PUBLISHED,
            },
        )
