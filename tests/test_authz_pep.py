"""Tests for project-mgmt as a pure Policy Enforcement Point:
  - UserMgmtClient.fetch_authz_context
  - get_caller_is_admin now derives from the projects:admin_override code
  - the middleware hydrates flat + scoped permissions from /authz/context
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.rbac import require_permission, require_project_permission
from app.dependencies import get_caller_is_admin
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.error_handler import register_exception_handlers
from app.services.user_mgmt_client import UserMgmtClient


# ----------------------------------------------------------------- client ----

def test_fetch_authz_context_unwraps_hal_and_forwards_auth():
    client = UserMgmtClient()
    client.base_url = "http://user-svc.test"
    client.timeout = 5.0
    with patch("app.services.user_mgmt_client.httpx.Client") as Client:
        inst = Client.return_value.__enter__.return_value
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": {"user_id": "u1", "permissions": ["projects:read"], "scoped": {}}}
        inst.get.return_value = resp

        ctx = client.fetch_authz_context("Bearer x")

        assert ctx == {"user_id": "u1", "permissions": ["projects:read"], "scoped": {}}
        assert inst.get.call_args.args[0] == "http://user-svc.test/api/v3/authz/context"
        assert inst.get.call_args.kwargs["headers"]["Authorization"] == "Bearer x"


def test_fetch_authz_context_401_returns_none():
    client = UserMgmtClient()
    client.base_url = "http://user-svc.test"
    with patch("app.services.user_mgmt_client.httpx.Client") as Client:
        Client.return_value.__enter__.return_value.get.return_value = MagicMock(status_code=401)
        assert client.fetch_authz_context("Bearer x") is None


# ----------------------------------------------------- get_caller_is_admin ---

def test_get_caller_is_admin_true_only_with_override_code():
    admin = SimpleNamespace(state=SimpleNamespace(user_permissions={"projects:admin_override"}))
    assert get_caller_is_admin(admin) is True

    pa = SimpleNamespace(state=SimpleNamespace(user_permissions={"projects:read", "projects:create"}))
    assert get_caller_is_admin(pa) is False

    anon = SimpleNamespace(state=SimpleNamespace(user_permissions=set()))
    assert get_caller_is_admin(anon) is False


# ------------------------------------------------------------- middleware ----

def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(AuthMiddleware)

    @app.get("/flat", dependencies=[Depends(require_permission("projects:read"))])
    def _flat():
        return {"ok": True}

    @app.get("/p/{project_uuid}", dependencies=[Depends(require_project_permission("projects:close"))])
    def _scoped():
        return {"ok": True}

    return app


def test_flat_gate_anonymous_401():
    assert TestClient(_app()).get("/flat").status_code == 401


def test_flat_gate_granted():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = {
            "user_id": "u1", "permissions": ["projects:read"], "scoped": {}, "vendor_id": None,
        }
        assert TestClient(_app()).get("/flat", headers={"Authorization": "Bearer x"}).status_code == 200


def test_scoped_gate_passes_with_project_scope():
    """A code scoped to project P1 authorizes the gate on /p/P1 (and the
    wire `project:P1` key is decoded back to the ("project", "P1") tuple)."""
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = {
            "user_id": "u1",
            "permissions": [],
            "scoped": {"project:P1": ["projects:close"]},
            "vendor_id": None,
        }
        resp = TestClient(_app()).get("/p/P1", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200


def test_scoped_gate_denied_for_other_project():
    """projects:close scoped to P1 must NOT authorize P2 (no scope-bleed)."""
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = {
            "user_id": "u1",
            "permissions": [],
            "scoped": {"project:P1": ["projects:close"]},
            "vendor_id": None,
        }
        resp = TestClient(_app()).get("/p/P2", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 403


def test_fails_closed_when_user_mgmt_unreachable():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.side_effect = RuntimeError("boom")
        assert TestClient(_app()).get("/flat", headers={"Authorization": "Bearer x"}).status_code == 401


# --------------------------------- project-list Doc-46 scoping via context ---

def test_project_list_scopes_to_context_project_ids(app):
    """A non-broad caller's project visibility is derived from the project
    scopes in their authz context (caller_project_ids), not a users.* read."""
    from app.dependencies import get_project_controller

    app.state.test_user_id = "u1"
    app.state.test_is_admin = False
    app.state.test_permissions = {"projects:read"}  # gate passes; NOT read_all
    app.state.test_scoped_permissions = {
        ("global", None): {"projects:read"},
        ("project", "P1"): {"projects:read"},
        ("project", "P2"): {"projects:read"},
    }

    fake = MagicMock()
    fake.list_.return_value = {"items": [], "total": 0, "offset": 1, "page_size": 20}
    app.dependency_overrides[get_project_controller] = lambda: fake
    try:
        resp = TestClient(app).get("/api/v3/projects")
        assert resp.status_code == 200
        kwargs = fake.list_.call_args.kwargs
        assert kwargs["caller_project_ids"] == {"P1", "P2"}
        assert kwargs["caller_can_see_all"] is False
        assert kwargs["caller_is_admin"] is False
    finally:
        app.dependency_overrides.pop(get_project_controller, None)


# --------------------------------- assignable-users picker via /authz/users ---

def test_fetch_users_builds_params_and_unwraps_collection():
    client = UserMgmtClient()
    client.base_url = "http://u.test"
    client.timeout = 5.0
    with patch("app.services.user_mgmt_client.httpx.Client") as C:
        inst = C.return_value.__enter__.return_value
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "data": {"_type": "Collection", "_embedded": {"elements": [{"id": "u1"}]}}
        }
        inst.get.return_value = resp

        out = client.fetch_users(
            authorization="Bearer x", vendor_ids=["V1", "V2"],
            role="org_admin", exclude_admin_tier=True,
        )

    assert out == [{"id": "u1"}]
    params = inst.get.call_args.kwargs["params"]
    assert ("vendor_id", "V1") in params and ("vendor_id", "V2") in params
    assert ("role", "org_admin") in params
    assert ("exclude_admin_tier", "true") in params


def test_assignable_picker_unions_sources_dedups_and_projects_org_role():
    from app.repositories.assignable_users_repository import AssignableUsersRepository

    repo = AssignableUsersRepository(MagicMock())
    repo.vendor_ids_for_project = MagicMock(return_value=["V1"])
    repo.division_codes_for_project = MagicMock(return_value={"D1"})

    with patch("app.repositories.assignable_users_repository.UserMgmtClient") as C:
        inst = C.return_value
        inst.fetch_users.side_effect = [
            [{"id": "u1", "login": "alice", "email": "a@x",
              "full_name": "Alice L", "roles": ["project_member"]}],     # (a) project
            [{"id": "u2", "login": "bob", "roles": ["org_admin"]}],      # (b) vendor member
            [{"id": "u1", "login": "alice", "roles": ["project_member"]}],  # (c) dup
        ]
        out = repo.list_assignable_users_for_project("P1", authorization="Bearer x")

    assert [u["id"] for u in out] == ["u1", "u2"]  # deduped, sorted by login
    assert out[0]["org_role"] == "project_member"
    assert out[1]["org_role"] == "org_admin"

    calls = inst.fetch_users.call_args_list
    assert calls[0].kwargs["project_id"] == "P1"
    assert calls[1].kwargs["vendor_ids"] == ["V1"]
    # Bug #142: branch (b) fetches ALL members of the project's vendor(s), not
    # just org_admins — so no role filter is sent.
    assert "role" not in calls[1].kwargs
    assert calls[2].kwargs["divisions"] == ["D1"]
    assert all(c.kwargs["exclude_admin_tier"] for c in calls)
