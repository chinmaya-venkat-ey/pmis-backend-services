"""
Shared write-lock helpers for milestones / activities / tasks / subtasks.

Every write path in those modules calls one of these guards before mutating
anything, so the rule for "can this project accept THIS kind of write right
now?" lives in one place.

Level semantics
---------------
Under the baseline/version split:

- A **baseline** project (``is_version=False``) owns its milestones and
  activities. Task and subtask rows must not be added to a baseline.
- A **version** project (``is_version=True``) is a fork of a published
  baseline. It inherits milestones and activities (via the clone at
  versioning time) but owns its own task / subtask rows. Milestones and
  activities on a version are driven by baseline propagation, not by
  direct writes.

Published baselines remain editable: changes applied to a baseline
propagate to its active versions (see ``cascade_baseline_*`` helpers).

Functions
---------
- ``assert_project_editable`` — project exists and is not soft-deleted.
  Used for any write that is allowed on both baselines and versions
  (e.g. restore, project-level updates).
- ``assert_milestone_activity_writable`` — project is a live baseline.
  Used for milestone / activity create / update / delete.
- ``assert_task_subtask_writable`` — project is a live version.
  Used for task / subtask create / update / delete.
"""
from sqlalchemy.orm import Session

from ..infrastructure.db.models.project import ProjectModel
from .errors import AuthorizationError, NotFoundError


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
    """
    Project exists and is not soft-deleted. No baseline/version check.

    Raises:
        NotFoundError: project does not exist, or has been soft-deleted.
    """
    _load_live_project(db, project_id)


def assert_milestone_activity_writable(db: Session, project_id: str) -> None:
    """
    Project accepts milestone / activity writes.

    Allowed only when the project is a live **baseline**. Versions reject
    the write — M/A changes must be applied to the baseline, which then
    propagates to active versions.

    Raises:
        NotFoundError: project missing or soft-deleted.
        AuthorizationError: project is a version.
    """
    project = _load_live_project(db, project_id)
    if getattr(project, "is_version", False):
        raise AuthorizationError(
            "Milestones and activities can only be added or modified on the "
            "baseline project, not on a version. Apply the change on the "
            "baseline — it will propagate to active versions automatically."
        )


def assert_task_subtask_writable(db: Session, project_id: str) -> None:
    """
    Project accepts task / subtask writes.

    Allowed only when the project is a live **version**. Baselines reject
    the write — tasks and subtasks belong to a version.

    Raises:
        NotFoundError: project missing or soft-deleted.
        AuthorizationError: project is a baseline.
    """
    project = _load_live_project(db, project_id)
    if not getattr(project, "is_version", False):
        raise AuthorizationError(
            "Tasks and subtasks can only be added or modified within a "
            "version. Create a version of this baseline first."
        )
