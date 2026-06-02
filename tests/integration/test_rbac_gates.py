"""Smoke tests for RBAC gates on project-svc endpoints.

Responses ride the canonical PMIS envelope ``{data, message, error,
status}``; tests read into ``error.errorIdentifier`` for failure codes
and ``data.*`` for success bodies.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def _err_code(payload: dict) -> str:
    return payload["error"]["errorIdentifier"]


def test_anonymous_cannot_list_projects(anonymous_client):
    resp = anonymous_client.get("/api/v3/projects")
    assert resp.status_code == 401
    assert _err_code(resp.json()) == "auth_required"


def test_anonymous_cannot_create_project(anonymous_client):
    resp = anonymous_client.post(
        "/api/v3/projects/create",
        json={"name": "P", "public": False, "vendor_ids": []},
    )
    assert resp.status_code == 401


def test_reader_can_list_projects(reader_client, app):
    """reader_client holds projects:read → list passes the auth gate."""
    from app.dependencies import get_project_controller

    fake_controller = MagicMock()
    fake_controller.list_.return_value = {
        "items": [], "total": 0, "offset": 1, "page_size": 20,
    }
    app.dependency_overrides[get_project_controller] = lambda: fake_controller
    try:
        resp = reader_client.get("/api/v3/projects")
        assert resp.status_code == 200
        # HAL Collection envelope under data.
        body = resp.json()["data"]
        assert body["_type"] == "Collection"
        assert body["total"] == 0
        assert body["_embedded"]["elements"] == []
    finally:
        app.dependency_overrides.pop(get_project_controller, None)


def test_reader_cannot_create_project(reader_client):
    """reader_client holds only `projects:read`; `projects:create` is required."""
    resp = reader_client.post(
        "/api/v3/projects/create",
        json={"name": "P", "public": False, "vendor_ids": []},
    )
    assert resp.status_code == 403
    assert _err_code(resp.json()) == "permission_denied"


def test_reader_cannot_delete_project(reader_client):
    resp = reader_client.delete("/api/v3/projects/some-uuid")
    assert resp.status_code == 403


def test_admin_can_list_projects(client, app):
    from app.dependencies import get_project_controller

    fake_controller = MagicMock()
    fake_controller.list_.return_value = {
        "items": [], "total": 0, "offset": 1, "page_size": 20,
    }
    app.dependency_overrides[get_project_controller] = lambda: fake_controller
    try:
        resp = client.get("/api/v3/projects")
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_project_controller, None)
