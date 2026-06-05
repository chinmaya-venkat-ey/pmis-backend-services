"""Unit tests for the user-management authz-context client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.user_mgmt_client import UserMgmtClient


def test_fetch_context_forwards_auth_and_unwraps_hal_data():
    with patch("app.services.user_mgmt_client.httpx.Client") as Client:
        inst = Client.return_value.__enter__.return_value
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "data": {"user_id": "u1", "permissions": ["files:read"], "scoped": {}},
            "error": None,
            "status": 200,
        }
        inst.get.return_value = resp

        ctx = UserMgmtClient(base_url="http://user-svc.test").fetch_authz_context("Bearer x")

        assert ctx == {"user_id": "u1", "permissions": ["files:read"], "scoped": {}}
        assert inst.get.call_args.args[0] == "http://user-svc.test/api/v3/authz/context"
        assert inst.get.call_args.kwargs["headers"]["Authorization"] == "Bearer x"


def test_fetch_context_401_returns_none():
    with patch("app.services.user_mgmt_client.httpx.Client") as Client:
        inst = Client.return_value.__enter__.return_value
        inst.get.return_value = MagicMock(status_code=401)

        ctx = UserMgmtClient(base_url="http://user-svc.test").fetch_authz_context("Bearer x")

        assert ctx is None


def test_fetch_context_no_base_url_returns_none():
    assert UserMgmtClient(base_url="").fetch_authz_context("Bearer x") is None
