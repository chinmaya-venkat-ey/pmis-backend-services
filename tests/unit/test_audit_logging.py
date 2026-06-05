"""Unit tests for the RBAC audit trail (F16): the repository insert and the
role-assignment service wiring."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.repositories.audit_log_repository import AuditLogRepository
from app.services.role_assignment_service import RoleAssignmentService


def test_audit_repository_record_inserts_row():
    db = MagicMock()
    repo = AuditLogRepository(db)

    repo.record(
        actor_user_id="caller",
        action="role_assignment.create",
        resource_type="user_role_assignment",
        resource_id="42",
        target_user_id="u1",
        after={"role": "project_member"},
    )

    db.add.assert_called_once()
    db.flush.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.actor_user_id == "caller"
    assert added.action == "role_assignment.create"
    assert added.resource_id == "42"
    assert added.target_user_id == "u1"
    assert added.after == {"role": "project_member"}


def _service_with_mocks():
    svc = RoleAssignmentService(MagicMock())
    svc.user_repo = MagicMock()
    svc.user_repo.get_by_id.return_value = SimpleNamespace(id="u1")
    svc.rbac = MagicMock()
    svc.rbac.get_role.return_value = SimpleNamespace(id=5, name="project_member")
    svc.repo = MagicMock()
    svc.repo.find_existing.return_value = None
    svc.repo.create.return_value = SimpleNamespace(id=42)
    svc.audit = MagicMock()
    svc._assert_caller_can_grant = MagicMock()  # gate verified elsewhere
    svc._to_response = MagicMock(return_value="resp")
    return svc


def test_role_assignment_create_writes_audit():
    svc = _service_with_mocks()
    payload = SimpleNamespace(
        user_id=None, role_id=5, project_ids=None, project_id="P1", organization_id=None,
    )

    svc.create(
        payload,
        target_user_id="u1",
        caller_user_id="caller",
        caller_is_admin=True,
    )

    svc.audit.record.assert_called_once()
    kwargs = svc.audit.record.call_args.kwargs
    assert kwargs["action"] == "role_assignment.create"
    assert kwargs["actor_user_id"] == "caller"
    assert kwargs["target_user_id"] == "u1"
    assert kwargs["resource_id"] == "42"
    assert kwargs["after"]["project_id"] == "P1"
    assert kwargs["after"]["role"] == "project_member"


def test_role_assignment_create_skips_audit_when_idempotent():
    """An already-existing (user, role, scope) is a no-op — no audit row."""
    svc = _service_with_mocks()
    svc.repo.find_existing.return_value = SimpleNamespace(id=99)  # already there
    payload = SimpleNamespace(
        user_id=None, role_id=5, project_ids=None, project_id="P1", organization_id=None,
    )

    svc.create(
        payload,
        target_user_id="u1",
        caller_user_id="caller",
        caller_is_admin=True,
    )

    svc.audit.record.assert_not_called()
    svc.repo.create.assert_not_called()
