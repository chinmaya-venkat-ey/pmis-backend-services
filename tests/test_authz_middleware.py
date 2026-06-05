"""Middleware tests: the gate flow end-to-end with the authz client mocked.

A minimal app (AuthMiddleware + one gated route) exercises the full
forward-token -> hydrate -> enforce path without DB/S3.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.rbac import require_permission
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.error_handler import register_exception_handlers


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(AuthMiddleware)

    @app.get("/files-read", dependencies=[Depends(require_permission("files:read"))])
    def _read():
        return {"ok": True}

    return app


def _ctx(perms):
    return {"user_id": "u1", "permissions": perms, "scoped": {}, "vendor_id": None}


def test_anonymous_denied():
    assert TestClient(_app()).get("/files-read").status_code == 401


def test_context_grants_permission():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = _ctx(["files:read"])
        resp = TestClient(_app()).get("/files-read", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200


def test_context_missing_permission_denied():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = _ctx(["files:create"])
        resp = TestClient(_app()).get("/files-read", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 403


def test_user_mgmt_unreachable_fails_closed():
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.side_effect = RuntimeError("boom")
        resp = TestClient(_app()).get("/files-read", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 401  # fail closed -> anonymous
