"""Unit tests for the Doc-24 nesting-depth guard in SubtaskService.

The cap comes from settings.subtask_max_nesting_depth (default 5). A new
nested subtask is rejected if its depth (parent's depth + 1) exceeds the cap.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import SubtaskNestingDepthExceededError
from app.schemas.subtask import SubtaskCreateRequest


def _payload(parent_subtask_id=None, task_id=None, name="Nested S"):
    return SubtaskCreateRequest(
        task_id=task_id,
        parent_subtask_id=parent_subtask_id,
        name=name,
        start_date="2026-05-15T00:00:00Z",
        end_date="2026-05-20T00:00:00Z",
    )


def test_nesting_depth_at_cap_rejected(monkeypatch):
    """If parent is already at depth=5 (max), creating a child would be depth=6 → reject."""
    from app.services import subtask_service as ss

    monkeypatch.setattr(ss.settings, "subtask_max_nesting_depth", 5, raising=False)
    svc = ss.SubtaskService(MagicMock())

    parent = MagicMock(id="s-parent", task_id="t-1", project_id="p-1")
    svc.get_by_id = MagicMock(return_value=parent)
    svc.repo.nesting_depth = MagicMock(return_value=5)  # parent is at depth 5

    with pytest.raises(SubtaskNestingDepthExceededError):
        svc.create(_payload(parent_subtask_id="s-parent"), caller_user_id="u-1")


def test_nesting_depth_just_below_cap_allowed(monkeypatch):
    from app.services import subtask_service as ss

    monkeypatch.setattr(ss.settings, "subtask_max_nesting_depth", 5, raising=False)
    svc = ss.SubtaskService(MagicMock())

    parent = MagicMock(id="s-parent", task_id="t-1", project_id="p-1")
    svc.get_by_id = MagicMock(return_value=parent)
    svc.repo.nesting_depth = MagicMock(return_value=4)  # depth 4 → child at 5, OK
    svc.repo.next_position_under_subtask = MagicMock(return_value=1)
    svc.repo.create = MagicMock(return_value=MagicMock(
        id="s-new", project_id="p-1", task_id="t-1",
        parent_subtask_id="s-parent", name="Nested S",
    ))
    svc.audit.write = MagicMock()
    svc.repo.replace_dependencies = MagicMock()
    svc.repo.upsert_resource = MagicMock()

    result = svc.create(_payload(parent_subtask_id="s-parent"), caller_user_id="u-1")
    assert result is not None
    svc.repo.create.assert_called_once()
