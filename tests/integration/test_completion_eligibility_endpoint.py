"""Integration tests for GET /api/v3/activities/{id}/completion-eligibility.

Confirms the route is wired, rides the canonical HAL envelope, and is
gated by ``activities:read`` (require_project_permission). The project-id
ancestor lookup (``_ancestor_project_id``) is monkeypatched so the gate
resolves a project without a live DB — matching how the other id-scoped
project-permission routes resolve scope from ``activity_id``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.schemas.activity import ActivityCompletionEligibilityResponse


_URL = "/api/v3/activities/a-1/completion-eligibility"


@pytest.fixture(autouse=True)
def _stub_project_resolution(monkeypatch):
    """Resolve activity_id -> project without a DB so the RBAC gate runs."""
    monkeypatch.setattr(
        "app.core.rbac._ancestor_project_id",
        lambda param_key, value: "proj-1",
    )


def _fake_controller():
    fake = MagicMock()
    fake.completion_eligibility.return_value = ActivityCompletionEligibilityResponse(
        activity_id="a-1",
        eligible=False,
        blocking_dependencies=[
            {"id": "a-2", "name": "Act 2", "status": "not_completed"},
        ],
    )
    return fake


def test_admin_gets_eligibility_in_hal_envelope(client, app):
    from app.dependencies import get_activity_controller

    app.dependency_overrides[get_activity_controller] = _fake_controller
    try:
        resp = client.get(_URL)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["_type"] == "ActivityCompletionEligibility"
        assert data["activityId"] == "a-1"
        assert data["eligible"] is False
        assert data["blockingDependencies"] == [
            {"id": "a-2", "name": "Act 2", "status": "not_completed"},
        ]
    finally:
        app.dependency_overrides.pop(get_activity_controller, None)


def test_anonymous_is_unauthorized(anonymous_client):
    resp = anonymous_client.get(_URL)
    assert resp.status_code == 401
    assert resp.json()["error"]["errorIdentifier"] == "auth_required"


def test_reader_without_activities_read_is_forbidden(reader_client):
    """reader_client holds only projects:read -> activities:read gate denies."""
    resp = reader_client.get(_URL)
    assert resp.status_code == 403
    assert resp.json()["error"]["errorIdentifier"] == "permission_denied"


def test_caller_with_activities_read_passes_gate(client, app):
    """A non-admin holding exactly activities:read globally passes the gate."""
    from app.dependencies import get_activity_controller

    app.state.test_user_id = "act-reader"
    app.state.test_is_admin = False
    app.state.test_permissions = {"activities:read"}
    app.state.test_scoped_permissions = {("global", None): {"activities:read"}}
    app.dependency_overrides[get_activity_controller] = _fake_controller
    try:
        resp = client.get(_URL)
        assert resp.status_code == 200
        assert resp.json()["data"]["activityId"] == "a-1"
    finally:
        app.dependency_overrides.pop(get_activity_controller, None)
