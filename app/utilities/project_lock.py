"""Project-write lock — gates which operations are allowed against a
project based on its lifecycle status.

Matches the monolith's ``app/core/project_lock.py`` semantics:

  * **Milestones + activities** are writable on every non-soft-deleted
    project regardless of status — they are part of "assembling the
    baseline" and may be edited at any time.
  * **Tasks + subtasks** can only be written when the project's status
    is ``published``. They are operational work units that only make
    sense once the baseline is locked in.

If a non-published project is reverted from ``published`` to ``draft``,
T/S writes lock again. Error message matches the monolith's
``publish_required`` errorIdentifier.
"""
from __future__ import annotations

from typing import Optional

from app.core.errors import ValidationError


def assert_project_writable(project) -> None:
    """``project`` is a live ``Project`` row (not soft-deleted)."""
    if project is None:
        raise ValidationError("The project could not be found.")
    if getattr(project, "deleted_at", None) is not None:
        raise ValidationError("The project has been deleted.")


def assert_milestone_activity_writable(project) -> None:
    """Milestones + activities can be written on any LIVE project,
    regardless of lifecycle status (matches monolith
    ``app/core/project_lock.py``)."""
    assert_project_writable(project)


def assert_task_subtask_writable(project) -> None:
    """Tasks + subtasks require the project to be in ``published``
    status (matches monolith
    ``app/core/project_lock.py:assert_task_subtask_writable``).

    Error message + ``errorIdentifier`` quoted verbatim from monolith.
    """
    assert_project_writable(project)
    status = (getattr(project, "status", None) or "").lower()
    if status != "published":
        # Monolith parity: the TOP-LEVEL ``errorIdentifier`` is the generic
        # ``ValidationError`` (TitleCase on /tasks /subtasks paths per the
        # per-module casing rule). The specific ``publish_required`` marker
        # lives INSIDE ``_embedded.details.errorIdentifier`` — clients that
        # want to discriminate the lock from other 422s key off that nested
        # field.
        raise ValidationError(
            "Tasks and subtasks can only be added to a published project. "
            "Publish the project first.",
            details={
                "errorIdentifier": "publish_required",
                "projectId": getattr(project, "id", None),
                "projectStatus": getattr(project, "status", None),
                "requiredStatus": "published",
            },
        )
