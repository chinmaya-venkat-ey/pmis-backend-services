"""Unit tests for the Doc-24 subtask nesting behavior.

Nesting is uncapped (matches the monolith). The repo's cascade walk has
its own seen-set so unbounded nesting is still safe for soft-delete /
restore. These tests check:

  * Top-level subtask under a task uses the task's project_id.
  * Nested subtask inherits the parent's task_id + project_id.
  * Either ``task_id`` OR ``parent_subtask_id`` must be supplied — not
    both, not neither.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.core.errors import SubtaskNotFoundError, ValidationError
from app.schemas.subtask import SubtaskCreateRequest


PROJECT_START = datetime(2026, 5, 1)
TASK_START = datetime(2026, 5, 10)


def _payload(name="S1"):
    return SubtaskCreateRequest(
        name=name,
        start_date=datetime(2026, 5, 15),
        end_date=datetime(2026, 5, 20),
        priority="P2",
    )


def _published_project(pid="p-1"):
    """Live project with status=published — passes the project-lock
    that the subtask service applies (monolith parity)."""
    return MagicMock(
        id=pid, status="published", start_date=PROJECT_START, deleted_at=None,
    )


def test_create_under_task_uses_task_project_id():
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    task = MagicMock(id="t-1", project_id="p-1", start_date=TASK_START)
    svc.tasks.get_by_id = MagicMock(return_value=task)
    svc.projects.get_by_id = MagicMock(return_value=_published_project())
    svc.repo.next_position_under_task = MagicMock(return_value=1)
    svc.repo.create = MagicMock(return_value=MagicMock(
        id="s-1", project_id="p-1", task_id="t-1",
        parent_subtask_id=None, name="S1",
    ))
    svc.comments.create = MagicMock()
    svc.audit.write = MagicMock()

    result = svc.create(_payload(), task_id="t-1", caller_user_id="u-1")
    assert result.project_id == "p-1"
    create_kwargs = svc.repo.create.call_args.kwargs
    assert create_kwargs["task_id"] == "t-1"
    assert create_kwargs["parent_subtask_id"] is None


def test_create_nested_inherits_parent_task_and_project():
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    parent = MagicMock(
        id="s-parent", task_id="t-1", project_id="p-1",
        parent_subtask_id=None, start_date=TASK_START,
    )
    svc.get_by_id = MagicMock(return_value=parent)
    svc.projects.get_by_id = MagicMock(return_value=_published_project())
    svc.repo.next_position_under_subtask = MagicMock(return_value=1)
    svc.repo.create = MagicMock(return_value=MagicMock(
        id="s-child", project_id="p-1", task_id="t-1",
        parent_subtask_id="s-parent", name="S1",
    ))
    svc.comments.create = MagicMock()
    svc.audit.write = MagicMock()

    result = svc.create(
        _payload(), parent_subtask_id="s-parent", caller_user_id="u-1",
    )
    assert result.task_id == "t-1"
    assert result.project_id == "p-1"
    create_kwargs = svc.repo.create.call_args.kwargs
    assert create_kwargs["parent_subtask_id"] == "s-parent"


def test_create_rejects_both_parents_supplied():
    """Both parents supplied is a 422 ValidationError (monolith parity —
    NOT a NotFound condition)."""
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    with pytest.raises(ValidationError):
        svc.create(
            _payload(),
            task_id="t-1",
            parent_subtask_id="s-parent",
            caller_user_id="u-1",
        )


def test_create_rejects_neither_parent_supplied():
    """Neither parent supplied is a 422 ValidationError (monolith parity)."""
    from app.services.subtask_service import SubtaskService

    svc = SubtaskService(MagicMock())
    with pytest.raises(ValidationError):
        svc.create(_payload(), caller_user_id="u-1")
