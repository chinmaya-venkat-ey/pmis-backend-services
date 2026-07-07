"""The finance page is gated by payment:read (admin/super_admin only).

A normal project member holding projects:read must be DENIED; only a caller
holding payment:read (granted solely to admin/super_admin) is allowed.
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.permissions import PAYMENT_READ
from app.core.rbac import require_project_permission
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.error_handler import register_exception_handlers


def _finance_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(AuthMiddleware)

    @app.get("/f/{project_uuid}", dependencies=[Depends(require_project_permission(PAYMENT_READ))])
    def _fin():
        return {"ok": True}

    return app


def _ctx(perms, scoped):
    return {"user_id": "u1", "permissions": perms, "scoped": scoped, "vendor_id": None}


def test_projects_read_alone_is_denied_the_finance_page():
    # A project member with projects:read (global + project-scoped) but NO
    # payment:read is now blocked from the finance page.
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = _ctx(
            ["projects:read"], {"project:P1": ["projects:read"]})
        resp = TestClient(_finance_app()).get("/f/P1", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 403


def test_payment_read_global_is_allowed():
    # admin/super_admin hold payment:read at GLOBAL scope -> allowed (same path
    # the existing projects:read gate uses for admins: scoped["global"]).
    with patch("app.middleware.auth_middleware.UserMgmtClient") as M:
        M.return_value.fetch_authz_context.return_value = _ctx(
            ["payment:read"], {"global": ["payment:read"]})
        resp = TestClient(_finance_app()).get("/f/P1", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 200


def test_anonymous_is_401():
    assert TestClient(_finance_app()).get("/f/P1").status_code == 401
