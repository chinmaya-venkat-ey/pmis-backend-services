"""Unit tests for ProjectService.save / publish / close — the three
explicit lifecycle verbs that replace the old FSM transition endpoint.

The contracts (mirroring the monolith):

  * ``save``    : ``new -> draft`` once at least one live milestone exists.
                  No-op when status is already past ``new``. Errors when
                  status is ``new`` and zero milestones exist.
  * ``publish`` : ``draft -> published`` (or any non-closed status to
                  published). No-op when already published. Errors if
                  the project is already closed.
  * ``close``   : ``* -> closed``. No-op when already closed. Optional
                  ``reason`` saved on the audit note.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.errors import ConflictError, ValidationError
from app.schemas.project import ProjectCloseRequest


def _make_project(*, project_id="p-1", status="draft"):
    row = MagicMock(name=f"Project({project_id})")
    row.id = project_id
    row.status = status
    row.project_id = project_id
    return row


# ----- save ---------------------------------------------------------------

def test_save_flips_new_to_draft_when_milestones_exist():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="new")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock(return_value=project)
    svc.audit.write = MagicMock()
    # Pretend the milestone-count query returns 1.
    svc.db.execute.return_value.scalar_one.return_value = 1

    result = svc.save("p-1", caller_user_id="u-1")
    assert result is project
    svc.repo.update.assert_called_once()
    kwargs = svc.repo.update.call_args.kwargs
    assert kwargs["status"] == "draft"


def test_save_is_no_op_when_past_new():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="published")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock()
    svc.audit.write = MagicMock()

    result = svc.save("p-1", caller_user_id="u-1")
    assert result is project
    svc.repo.update.assert_not_called()


def test_save_rejects_when_new_but_no_milestones():
    """Monolith parity: missing-milestone is a 422 ``ValidationError``,
    not 409 (see PMIS-OpenProject/tests/test_projects.py:107-113)."""
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="new")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock()
    svc.audit.write = MagicMock()
    svc.db.execute.return_value.scalar_one.return_value = 0  # zero milestones

    with pytest.raises(ValidationError) as exc:
        svc.save("p-1", caller_user_id="u-1")
    assert exc.value.status_code == 422
    assert "milestone" in exc.value.message.lower()
    svc.repo.update.assert_not_called()


# ----- publish ------------------------------------------------------------

def test_publish_flips_draft_to_published():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="draft")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock(return_value=project)
    svc.audit.write = MagicMock()

    result = svc.publish("p-1", caller_user_id="u-1")
    assert result is project
    kwargs = svc.repo.update.call_args.kwargs
    assert kwargs["status"] == "published"


def test_publish_already_published_returns_409():
    """Monolith parity: re-publishing an already-published project raises
    409 ``ConflictError`` (see PMIS-OpenProject/tests/test_projects.py:150-155
    which asserts ``second.status_code == 409``)."""
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="published")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock()
    svc.audit.write = MagicMock()

    with pytest.raises(ConflictError) as exc:
        svc.publish("p-1", caller_user_id="u-1")
    assert exc.value.status_code == 409
    assert exc.value.code == "invalid_transition"
    svc.repo.update.assert_not_called()


def test_publish_rejects_when_already_closed():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="closed")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock()
    svc.audit.write = MagicMock()

    with pytest.raises(ConflictError):
        svc.publish("p-1", caller_user_id="u-1")
    svc.repo.update.assert_not_called()


# ----- close --------------------------------------------------------------

def test_close_flips_to_closed_with_reason():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="published")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock(return_value=project)
    svc.audit.write = MagicMock()

    result = svc.close(
        "p-1", ProjectCloseRequest(reason="finished early"),
        caller_user_id="u-1",
    )
    assert result is project
    audit_kwargs = svc.audit.write.call_args.kwargs
    assert audit_kwargs["action"] == "close"
    assert audit_kwargs["note"] == "finished early"


def test_close_no_op_when_already_closed():
    from app.services.project_service import ProjectService

    svc = ProjectService(MagicMock())
    project = _make_project(status="closed")
    svc.repo.get_by_id = MagicMock(return_value=project)
    svc.repo.update = MagicMock()
    svc.audit.write = MagicMock()

    result = svc.close("p-1", None, caller_user_id="u-1")
    assert result is project
    svc.repo.update.assert_not_called()
