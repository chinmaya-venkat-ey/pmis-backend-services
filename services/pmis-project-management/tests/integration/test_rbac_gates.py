"""Smoke tests for RBAC gates on project-svc endpoints.

Confirms:
  - Anonymous callers get 401 on protected list/create endpoints
  - Non-admin readers holding only `projects:read` can list but not create
  - Admin (test default) bypasses per-permission checks
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_anonymous_cannot_list_projects(anonymous_client):
    resp = anonymous_client.get("/project/projects/list")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"


def test_anonymous_cannot_create_project(anonymous_client):
    resp = anonymous_client.post(
        "/project/projects/create",
        json={"name": "P", "public": False, "vendor_ids": []},
    )
    assert resp.status_code == 401


def test_reader_can_list_projects(reader_client, app):
    """reader_client holds projects:read → list_ passes the global gate."""
    from app.dependencies import get_project_controller

    fake_controller = MagicMock()
    fake_controller.list_.return_value = {
        "items": [], "total": 0, "offset": 1, "page_size": 20,
    }
    app.dependency_overrides[get_project_controller] = lambda: fake_controller
    try:
        resp = reader_client.get("/project/projects/list")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0
    finally:
        app.dependency_overrides.pop(get_project_controller, None)


def test_reader_cannot_create_project(reader_client):
    """reader_client holds `projects:read` only — `projects:create` is required."""
    resp = reader_client.post(
        "/project/projects/create",
        json={"name": "P", "public": False, "vendor_ids": []},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PERMISSION_DENIED"


def test_reader_cannot_delete_project(reader_client):
    resp = reader_client.delete("/project/projects/some-uuid/delete")
    assert resp.status_code == 403


def test_admin_can_list_projects(client, app):
    from app.dependencies import get_project_controller

    fake_controller = MagicMock()
    fake_controller.list_.return_value = {
        "items": [], "total": 0, "offset": 1, "page_size": 20,
    }
    app.dependency_overrides[get_project_controller] = lambda: fake_controller
    try:
        resp = client.get("/project/projects/list")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_project_controller, None)
