"""Unit tests for ProjectService.transition_status — the FSM gate.

The transition reads the masters.project_status_transitions catalog via
ProjectStatusTransitionRepository. Admins bypass the role check; non-admins
need an active edge that matches their role (or a role-unscoped edge).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import InvalidStatusTransitionError
from app.schemas.project import ProjectStatusTransitionRequest


def _make_project(*, project_id="p-1", status="draft"):
    row = MagicMock(name=f"Project({project_id})")
    row.id = project_id
    row.status = status
    row.project_id = project_id
    return row


def test_admin_bypasses_role_check_on_transition():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="draft")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock(return_value=project)
    svc.transitions.is_allowed = MagicMock(return_value=False)
    svc.audit.write = MagicMock()

    result = svc.transition_status(
        "p-1",
        ProjectStatusTransitionRequest(to_status="published"),
        caller_user_id="admin-uid",
        caller_is_admin=True,
        caller_role_name=None,
    )
    assert result is project
    svc.repo.update.assert_called_once()
    # admin path skips the FSM lookup entirely
    svc.transitions.is_allowed.assert_not_called()


def test_non_admin_blocked_when_fsm_rejects():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="draft")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.transitions.is_allowed = MagicMock(return_value=False)
    svc.repo.update = MagicMock()

    with pytest.raises(InvalidStatusTransitionError) as exc:
        svc.transition_status(
            "p-1",
            ProjectStatusTransitionRequest(to_status="closed"),
            caller_user_id="u-9",
            caller_is_admin=False,
            caller_role_name="project_admin",
        )
    assert "draft" in exc.value.details["from_status"]
    assert exc.value.details["to_status"] == "closed"
    svc.repo.update.assert_not_called()


def test_no_op_when_to_status_equals_current():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="published")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock()
    svc.transitions.is_allowed = MagicMock()

    result = svc.transition_status(
        "p-1",
        ProjectStatusTransitionRequest(to_status="published"),
        caller_user_id="u-9",
        caller_is_admin=False,
        caller_role_name="org_admin",
    )
    assert result is project
    svc.repo.update.assert_not_called()
    svc.transitions.is_allowed.assert_not_called()
