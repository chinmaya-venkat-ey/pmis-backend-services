"""Tests for the user-management authz client + the PEP middleware flow.

Builds its own minimal app with the REAL AuthMiddleware (the shared conftest
fixtures swap it out, so they aren't used here)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.core.rbac import require_permission
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.error_handler import register_exception_handlers
from app.services.user_mgmt_client import UserMgmtClient


# ----------------------------------------------------------------- client ----

def test_client_forwards_auth_and_unwraps_hal_data():
    with patch("app.services.user_mgmt_client.httpx.Client") as Client:
        inst = Client.return_value.__enter__.return_value
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"data": {"user_id": "u1", "permissions": ["divisions:read"], "scoped": {}}}
        inst.get.return_value = resp

        ctx = UserMgmtClient(base_url="http://user-svc.test").fetch_authz_context("Bearer x")

        assert ctx == {"user_id": "u1", "permissions": ["divisions:read"], "scoped": {}}
        assert inst.get.call_args.args[0] == "http://user-svc.test/api/v3/authz/context"
        assert inst.get.call_args.kwargs["headers"]["Authorization"] == "Bearer x"


def test_client_401_returns_none():
    with patch("app.services.user_mgmt_client.httpx.Client") as Client:
        Client.return_value.__enter__.return_value.get.return_value = MagicMock(status_code=401)
        assert UserMgmtClient(base_url="http://user-svc.test").fetch_authz_context("Bearer x") is None


def test_client_no_base_url_returns_none():
    assert UserMgmtClient(base_url="").fetch_authz_context("Bearer x") is None


# ------------------------------------------------------------- middleware ----

def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(AuthMiddleware)

    @app.get("/d", dependencies=[Depends(require_permission("divisions:read"))])
    def _read():
        return {"ok": True}

    return app


def _ctx(perms, vendor_id=None):
    return {"user_id": "u1", "permissions": perms, "scoped": {}, "vendor_id": vendor_id}


def test_anonymous_denied():
    assert TestClient(_app()).get("/d").status_code == 401


def test_context_grants_permission():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = _ctx(["divisions:read"])
        assert TestClient(_app()).get("/d", headers={"Authorization": "Bearer x"}).status_code == 200


def test_context_missing_permission_denied():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = _ctx(["divisions:manage"])
        assert TestClient(_app()).get("/d", headers={"Authorization": "Bearer x"}).status_code == 403


def test_vendor_id_hydrated_as_user_vendor_id():
    """The context's vendor_id must land on request.state.user_vendor_id
    (VendorService reads that exact field for row-scoping)."""
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(AuthMiddleware)

    @app.get("/whoami")
    def _whoami(request: Request):
        return {"user_vendor_id": getattr(request.state, "user_vendor_id", None)}

    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = _ctx(["divisions:read"], vendor_id="V9")
        resp = TestClient(app).get("/whoami", headers={"Authorization": "Bearer x"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["user_vendor_id"] == "V9"


def test_user_mgmt_unreachable_fails_closed():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.side_effect = RuntimeError("boom")
        assert TestClient(_app()).get("/d", headers={"Authorization": "Bearer x"}).status_code == 401
